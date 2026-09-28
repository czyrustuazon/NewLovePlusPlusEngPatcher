# SpotPass rebuild

One service owns the week. Players send comments, photos, and spot notes in. The service stores them, and on a cut it writes one `info.dat`. Every console then replaces the previous issue with that file. The 2012 CDN did the same job as two task names (`ITASK01` in, `PTASK01` out) on one host. This plan keeps that shape. Addresses and payload facts below are the ones already recorded in `technical.md` §16.

The current patch does not need this service. `src/patch_spotpass_embed.py` already plants issue 28 and spoofs the two BOSS replies. The service is how more than one player’s upload becomes the next week.

## One place

| Direction | What it is | What the console sees |
|-----------|------------|------------------------|
| Inbox | Comments, photos, spot notes | Nothing, until the next cut |
| Weekly file | One `info.dat` for NsDataId **1** | The magazine, the city voices, and the city update |
| Delivery | Bake / embed, or a BOSS task that serves that same file | One slot. The next week replaces it |

Missed weeks are not backfilled. The book does not keep a stack. Page arrows walk the filled corners of the current file (the mask at `[magazine+0x8c]`), not earlier issues.

A public Pretendo network is not this place. Their BOSS server delivers notifications, StreetPass relay, WaraWara Plaza, and Splatoon rotations. It does not serve this title. A self-hosted copy of that server can be the delivery shelf for task `QwyHOPV4LsvQ2I3U` later. It does not parse uploads, and it does not fix the merge crash.

## Already known

### The download the client already performs

| Item | Value |
|------|--------|
| Title | `00040000000F4E00` |
| Boss extdata | `0x321` (`extdata/00000000/00000321/boss/info.dat`) |
| NsDataId | **1** |
| Datatype | `0x10001` |
| Payload version on the ++ file | `0x500` |
| Task | `QwyHOPV4LsvQ2I3U` |
| CDN path | `https://npdl.cdn.nintendowifi.net/p01/nsa/QwyHOPV4LsvQ2I3U/` |
| Task names in the client | `PTASK01`, `PTASK02` |
| Read path | `GetNsDataNewFlag` `FUN_00609ab0` @ `0x00609AB0`; `SpotPass_TryReadNsData` @ `0x00609C98`; buffer `0x7D004` |

`tools/build_spotpass_inject.py` wraps the raw payload in the 0x34-byte header the sysmodule stores. Hardware wants the exact file (2376 bytes). Azahar’s stock HLE wants either a short-read clamp or the padded blob.

### What one weekly file contains

The boot line is the apply prompt for one blob. That blob is the magazine, the city voices (街の声), and the city changes (街の変化): which spots are busy, which shops open or close, and the meal rankings. Real-place trips are not in it. Nikko, Kinugawa, Hakone, and Atami are on the cart. Enoshima is on the cart for this title (script `t146`, extra data `00000f4e`). The 2012 heroine distribution packs are not applied here.

Two surviving files:

| File | Size | What it is |
|------|------|------------|
| `tools/spotpass/info.dat` | 2,324 | Love Plus+ payload. Labels itself 第28号. Six city comments, one lake paragraph, one heated-pool paragraph. No photo-contest JPEGs. |
| 2012 `PTASK01` `info.dat` | 400,453 | The magazine still on that server, 2014-03-17. Indoor-pool holy site, fountain-park paragraph, short city comments, and 20 photo-contest JPEGs of about 20 KB each. NsDataId 1, version `0x215`, program id `0004000000032100`. |

The six ++ comments are the citizen channel, each signed とわの市の人々, places 1, 2, 3, 4, 6, and 28. They are drawn by the bubble cave, not by the merge. The lake sentence is Holy Site (banner index 1). The pool sentence is FEVER (banner index 3). The live page mask is `0x0A`.

Issue 28 is the label inside the last ++ file the CDN still had. It is not proof the series was numbered through a final issue.

### How the console keeps a week

`ReadNsData` loads one payload. The next week replaces that slot. The copy already on the console stays readable until then. The 2012 public archive holds one magazine file, repeated per region (1,596 copies of the same `info.dat.boss`). The ++ archive holds one unique payload, also repeated per region. The rest of the 2012 mirror is `ITASK01` / `dateeditNNNNN.boss`, about 946,292 bytes each, copied per region. That mirror is not a catalog to rehost.

### What the patch does instead of a server

| Piece | Role |
|-------|------|
| Payload at `0x006FBB08` | The 2,324-byte file. Data only. Not executable. |
| `FUN_00609ab0` | Always returns 1, so apply can start. |
| ReadNsData BLs @ `0x00609FD8` / `0x0060A018` | Copy the payload. Do not write `wrapper+0x200`. |
| `FUN_006088c8` | `mov r0,#1; bx lr`. The merge does not run. |
| Bubble cave @ `0x00608930` | On pack `0xB105`, copy one of the six file lines over the body. Index modulo 6. Lives in the dead merge body and stops before the `ac:u` site at `0x006089EC`. |
| Name and sentence caves | 「湖」 / 奥十羽野駅, and the two paragraphs in `Tex_Info_01`. The stubbed merge never fills those buffers. |

Un-stubbing the merge crashes. Skip-`ac:u` still lets WaitSync latch `+0x250=1` on a bad handle. The next tick `bl FUN_004e19b0` @ `0x00608984` jumps through garbage. The other branch maps a MemoryBlock with `svc 0x24`. A downloaded file does not create that handle. The comment cave has to move before the entry can be vanilla again. The other early-return stubs (`0x006090B0` through `0x00609600`) also hold caves, and the executable pad those caves use is full.

## Still to map

These are the gaps that block a live week. The first three are the upload. The rest are the apply.

| Gap | Why it blocks |
|-----|----------------|
| The upload call | The client function that posts a comment, a photo, or a spot note is not located. Without it, the game cannot send into the inbox. A manual inbox does not need it. |
| `dateedit` layout | The 2012 blobs are the stored uploads. Their fields are not parsed. Unique payload versus regional duplicate is known only as file size and path. |
| `PTASK01` versus `PTASK02` | Both names are in the client. Which one is the magazine, which one is the upload, and the task policy (URL, interval, file list) are not. |
| Rest of `info.dat` | Six voice records and two paragraphs are parsed. Busy-spot bits, shop open/close, and meal-rank tables inside the 2,324-byte file are not. |
| Photo-contest path on ++ | The 2012 magazine carried 20 JPEGs and pointed at Camera → Photo Contest. The ++ file has none. Whether this title still has a slot for them is open. |
| Merge outputs | Once `ac:u` has a real handle, what `FUN_006088c8` writes into the magazine record, the city tables, and the meal tables. Today those shows are caves. |
| Hardware “new” flag | A file under `boss/` is not enough on a console. The sysmodule database has to mark NsDataId 1 new. Azahar invents that flag. |

## Architecture

```
players  --->  inbox  --->  week cutter  --->  one info.dat
                              |                      |
                              |                      +--> bake / embed (current consoles)
                              |                      +--> BOSS shelf, NsDataId 1 (stock download)
                              |
                              +--> kept notes that did not make this week
```

The inbox stores a post until a person, or a later job, cuts a week. A cut selects which corners have articles, copies the chosen voices into the six-line table, writes the holy-site and FEVER sentences, and, once those fields are mapped, the shop and meal tables. It publishes one file. Old files stay on the service for the record. The console only fetches the current one.

Two shelves, one file:

- **Bake / embed.** What ships today. The week is in `code.bin` and the name-input rebuild. Right for the English patch and for Azahar, because LayeredFS cannot overlay boss extdata and a CIA install cannot write `00000321/boss/`.
- **BOSS shelf.** The same bytes behind task `QwyHOPV4LsvQ2I3U`, so a stock client’s `ReadNsData` fills NsDataId 1. Self-hosted Pretendo BOSS can be this shelf after the console’s BOSS key is available. It is optional. It does not replace the inbox or the week cutter.

Apply stays in the client. The service never draws the book.

- Now: the bubble cave and the sentence caves read the fields we know.
- Later: move those caves out of the stubbed bodies, fix the `ac:u` handle, and let `FUN_006088c8` fill the records. The caves come out when the stock fill draws the same corners. Both at once will fight over the panes.

## Order of work

1. **Manual week.** Accept a comment by hand. Put it in the six-line table the bubble cave already copies. Ship that `info.dat` in the next bake. This proves the one-file cut without the upload protocol.
2. **Name the rest of the 2,324-byte file.** Mark which bytes are voices, paragraphs, and anything that looks like a shop, a spot, or a meal rank. Extend a cave only for a field that is identified.
3. **Find the upload call** and the `dateedit` record it matches. Point a test build at the inbox. Store the post. Do not promise it appears in the city until step 4 or 5 writes it into a record the viewer reads.
4. **Cut a week from the inbox** into one `info.dat`, and deliver it by the embed. Voices and the two articles are the first cut. Shops, busy spots, meals, and photos join the cutter as their fields are known.
5. **Decide the merge.** If the stock function accepts this file, move the caves, repair the handle, and delete the caves that the merge replaces. If it only accepts the 400 KB 2012 magazine, keep the caves as the ++ apply path.
6. **BOSS shelf, if a stock console should download.** Publish the current file as NsDataId 1. Leave the embed in place for the English build.

Step 1 is the service. Steps 2–4 are the mapping. Step 5 is the crash that is already located. Step 6 is delivery, and it can wait.
