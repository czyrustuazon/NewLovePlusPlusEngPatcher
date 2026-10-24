/* Romaji Called-name lookup (Profile / first-boot 呼ばれ方 list).
 *
 * Replaces the bodies of FUN_00147b3c (exact lookup) and FUN_00147e04
 * (candidate list). The shipped TRB romanizes pack 0x7200 ("Akiko"), so the
 * vanilla hiragana bucket walk (pack 0x7000 first kana -> 0x7100+bucket) can
 * no longer match anything. These two functions search pack 0x7200 directly
 * over the vanilla ID ranges, case-insensitively, and return the same out
 * structs, so Call01 / Call02 still draw the text and store the reading ID
 * the heroine's voice uses.
 *
 * Fuzzy scoring follows media-kit js/fuzzy.js (master-music-player search):
 * prefix match first, then typos by optimal string alignment distance (one
 * slip for 4-7 letters, two for 8+) against the whole reading. Two fuzzy.js
 * rules are left out: subsequences (on 4-6 letter names they match almost
 * everything) and typos against a reading's beginning ("Taro" listed Tanoe,
 * Tamotsu, Tanokura); names are typed in full.
 *
 * Freestanding ARM (armv6k, ARM state). No globals, no libc: game data and
 * the TRB getter are fixed VAs. Built by tools/build_call_romaji_match.py
 * into src/call_romaji_match_blob.py; never edit the blob by hand.
 */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

/* FUN_005c0d4c: (pack, slot, 1) -> NUL-terminated UTF-8 string or 0. */
typedef const char *(*get_str_fn)(u32 pack, u32 slot, u32 one);
#define GET_STR ((get_str_fn)0x006C0D4Cu)
/* FUN_000317dc: the strncpy the Call01 / Call02 tap handlers use. */
typedef void (*copy_fn)(char *dst, const char *src, u32 n);
#define COPY ((copy_fn)0x001317DCu)
/* Seven inclusive (lo, hi) ID ranges in pack 0x7200 (FUN_00147b3c pool). */
#define RANGES ((const volatile u16 *)0x007A484Eu)
#define RANGE_COUNT 7
/* IDs mode 1 (Profile Call01) rejects (FUN_00147b3c pool, 0x17 entries). */
#define EXCLUDED ((const volatile u16 *)0x007A4986u)
#define EXCLUDED_COUNT 23

#define PACK 0x7200u
#define MAXLEN 32  /* normalized letters + NUL */
#define KEEP 10    /* Call01 / Call02 draw at most 10 rows */

#define SCORE_EXACT 1000
#define SCORE_PREFIX 500
#define SCORE_TYPO 400
#define SCORE_LONGER 300

/* scan kinds */
#define FUZZY 0
#define EXACT 1
#define LOOSE 2 /* exact after collapse(): Yuji finds ゆうじ "Yuuji" */

/* Typed names with no reading are listed with this suffix; the tap handler
 * strips it before the name is saved (nlpp_call_pick). */
#define NO_VOICE " *"
#define TYPED_MAX 32 /* Call02's text slot and the stack buffer hold 0x20 */

/* Lower-case ASCII letters only. ō / é fold to o / e; other non-ASCII and
 * punctuation (Shin'ichi, Kyō-chan) are dropped. Returns -1 if too long. */
static int normalize(const char *s, char *out)
{
    int n = 0;
    while (*s) {
        u8 c = (u8)*s++;
        if (c >= 0x80) {
            u8 d = (u8)*s;
            if (c == 0xC5 && d == 0x8D)
                c = 'o';
            else if (c == 0xC3 && d == 0xA9)
                c = 'e';
            else
                c = 0;
            while (((u8)*s & 0xC0) == 0x80)
                s++;
        } else if (c >= 'A' && c <= 'Z') {
            c += 'a' - 'A';
        }
        if (c < 'a' || c > 'z')
            continue;
        if (n >= MAXLEN - 1)
            return -1;
        out[n++] = (char)c;
    }
    out[n] = 0;
    return n;
}

/* The typed name, normalized. 0 when empty, not pure ASCII, or too long. */
static int query(const char *name, char *q)
{
    const char *p;
    int n;
    if (!name)
        return 0;
    for (p = name; *p; p++)
        if ((u8)*p >= 0x80)
            return 0;
    n = normalize(name, q);
    return n > 0 ? n : 0;
}

static int same(const char *a, const char *b, int n)
{
    int i;
    for (i = 0; i < n; i++)
        if (a[i] != b[i])
            return 0;
    return 1;
}

static int excluded(u32 mode, u32 id)
{
    int i;
    if (mode != 1)
        return 0;
    for (i = 0; i < EXCLUDED_COUNT; i++)
        if (EXCLUDED[i] == id)
            return 1;
    return 0;
}

/* Optimal string alignment distance (Levenshtein plus adjacent swaps),
 * giving up once it exceeds max. noinline keeps it in region A: inlined,
 * scan outgrows region C. */
__attribute__((noinline)) static int distance(const char *a, int n, const char *b, int m, int max)
{
    u8 r0[MAXLEN + 1], r1[MAXLEN + 1], r2[MAXLEN + 1];
    u8 *pp = r0, *p = r1, *c = r2, *t;
    int i, j;
    if (n - m > max || m - n > max)
        return max + 1;
    for (j = 0; j <= m; j++)
        p[j] = (u8)j;
    for (i = 1; i <= n; i++) {
        int row_min = i;
        c[0] = (u8)i;
        for (j = 1; j <= m; j++) {
            int v = p[j] + 1;
            int w = c[j - 1] + 1;
            int x = p[j - 1] + (a[i - 1] != b[j - 1]);
            if (w < v)
                v = w;
            if (x < v)
                v = x;
            if (i > 1 && j > 1 && a[i - 1] == b[j - 2] && a[i - 2] == b[j - 1]
                && pp[j - 2] + 1 < v)
                v = pp[j - 2] + 1;
            c[j] = (u8)v;
            if (v < row_min)
                row_min = v;
        }
        if (row_min > max)
            return max + 1;
        t = pp;
        pp = p;
        p = c;
        c = t;
    }
    return p[m];
}

/* q (n letters) typed, t (m letters) a reading that is not equal to q. */
static int score(const char *q, int n, const char *t, int m)
{
    int max = n >= 8 ? 2 : (n >= 4 ? 1 : 0);
    int d;
    if (n >= 2 && m > n && same(q, t, n))
        return SCORE_PREFIX - (m - n);
    if (max) {
        d = distance(q, n, t, m, max);
        if (d <= max)
            return SCORE_TYPO - 50 * d - (m > n ? m - n : n - m);
    }
    if (m >= 3 && n > m && same(q, t, m))
        return SCORE_LONGER - (n - m);
    return 0;
}

/* FNV-1a of a normalized reading. Equal readings under different IDs
 * ("Aki" is both 582 and 3186) are listed once. */
static u32 hash(const char *t)
{
    u32 h = 2166136261u;
    while (*t)
        h = (h ^ (u8)*t++) * 16777619u;
    return h;
}

/* Long vowels as one letter, in place: uu -> u, ou / oo -> o. Returns the
 * new length. Only for LOOSE: Ono / Oono are different readings. */
static int collapse(char *t)
{
    int i, n = 0;
    for (i = 0; t[i]; i++) {
        if (n && t[n - 1] == t[i] && (t[i] == 'u' || t[i] == 'o'))
            continue;
        if (n && t[n - 1] == 'o' && t[i] == 'u')
            continue;
        t[n++] = t[i];
    }
    t[n] = 0;
    return n;
}

/* Fills out[0] = count, out[1..] = IDs, best first (at most keep). EXACT /
 * LOOSE: only readings equal to the typed name; FUZZY: suggestions without
 * the exact reading. */
static void scan(const char *name, u32 mode, int kind, int *out, int keep)
{
    char q[MAXLEN], t[MAXLEN];
    int ids[KEEP], scores[KEEP];
    u32 hashes[KEEP];
    int n, m, r, i, k = 0;
    out[0] = 0;
    out[1] = -1;
    n = query(name, q);
    if (!n)
        return;
    if (kind == LOOSE)
        n = collapse(q);
    for (r = 0; r < RANGE_COUNT; r++) {
        u32 id, hi = RANGES[2 * r + 1];
        for (id = RANGES[2 * r]; id <= hi; id++) {
            const char *s;
            u32 h;
            int v, at;
            if (excluded(mode, id))
                continue;
            s = GET_STR(PACK, id, 1);
            if (!s)
                continue;
            m = normalize(s, t);
            if (m <= 0)
                continue;
            if (kind == LOOSE)
                m = collapse(t);
            if (m == n && same(q, t, n))
                v = kind != FUZZY ? SCORE_EXACT : 0;
            else
                v = kind != FUZZY ? 0 : score(q, n, t, m);
            if (!v)
                continue;
            h = hash(t);
            for (i = 0; i < k && hashes[i] != h; i++)
                ;
            if (i < k)
                continue;
            /* Insert after equal scores so ID order breaks ties. */
            for (at = k; at > 0 && scores[at - 1] < v; at--)
                ;
            if (at >= keep)
                continue;
            if (k < keep)
                k++;
            for (i = k - 1; i > at; i--) {
                ids[i] = ids[i - 1];
                scores[i] = scores[i - 1];
                hashes[i] = hashes[i - 1];
            }
            ids[at] = (int)id;
            scores[at] = v;
            hashes[at] = h;
        }
    }
    for (i = 0; i < k; i++)
        out[1 + i] = ids[i];
    out[0] = k;
}

/* FUN_00147b3c(name, mode, out): out[0] = 1 and out[1] = ID on a match.
 * Vanilla never matches mode >= 3. */
int nlpp_call_exact(const char *name, u32 mode, int *out)
{
    if (mode >= 3) {
        out[0] = 0;
        out[1] = -1;
        return 0;
    }
    scan(name, mode, EXACT, out, 1);
    return out[0];
}

/* FUN_00147e04(name, mode, flag, out). flag 0 (Called list): fuzzy
 * suggestions; the caller already drew the exact match from
 * nlpp_call_exact. flag != 0 (two-name compare at 0x2a601c): exact matches
 * only. Vanilla clamps mode >= 3 to 1. */
void nlpp_call_list(const char *name, u32 mode, u32 flag, int *out)
{
    scan(name, mode >= 3 ? 1 : mode, flag != 0 ? EXACT : FUZZY, out, KEEP);
}

/* Typed-name row (exact lookup missed; called from the patch cave). Returns
 * the reading ID of a long-vowel match (YUji -> 550 ゆうじ "Yuuji") so she
 * says it while the row keeps the typed text, else -1. Writes the row text to
 * buf (TYPED_MAX bytes): the name, plus NO_VOICE when there is no reading. */
int nlpp_call_typed(const char *name, u32 mode, char *buf)
{
    int out[2], i = 0, j;
    scan(name, mode >= 3 ? 1 : mode, LOOSE, out, 1);
    while (name[i] && i < TYPED_MAX - (int)sizeof(NO_VOICE)) {
        buf[i] = name[i];
        i++;
    }
    if (!out[0])
        for (j = 0; NO_VOICE[j]; j++)
            buf[i++] = NO_VOICE[j];
    buf[i] = 0;
    return out[0] ? out[1] : -1;
}

/* Replaces the tap handlers' copy of a row's text into the Called name
 * (0x23e73c Call01, 0x1f1d20 Call02): the same strncpy, then NO_VOICE is
 * dropped so the saved name and dialogue never show it. */
void nlpp_call_pick(char *dst, const char *src, u32 n)
{
    int len = 0;
    COPY(dst, src, n);
    while (len < (int)n && dst[len])
        len++;
    if (len >= 2 && dst[len - 2] == NO_VOICE[0] && dst[len - 1] == NO_VOICE[1])
        dst[len - 2] = 0;
}
