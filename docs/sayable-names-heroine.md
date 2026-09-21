# Heroine voice tokens (`code.bin`)

Hardcoded katakana the girls can speak for **themselves**, plus special confession / apology lines and stock family / greeting tokens.

File offsets are vanilla `extracted/exefs/code.bin` (Ghidra image base 0). Runtime VA = file + `0x100000`.

Pointer table: **`0x7A57F0`**. String blob: **`0x73FD32`–`0x740036`**.

## Manaka Takane

| Katakana | English | Kind |
|----------|---------|------|
| タカネ | Takane | family |
| マナカ | Manaka | given |
| マナチャン | Mana-chan | nick |
| タカネチャン | Takane-chan | nick |
| マナカチャン | Manaka-chan | nick |
| マナクン | Mana-kun | nick |
| タカネクン | Takane-kun | nick |
| タカネサン | Takane-san | nick |
| マナカサン | Manaka-san | nick |
| マナカゴメンナサイ | Manaka — I'm sorry | special |
| マナカアイシテルヨ | Manaka — I love you | special |
| マナカガイチバンダイスキ | I love Manaka the most | special |

## Rinko Kobayakawa

| Katakana | English | Kind |
|----------|---------|------|
| コバヤカワ | Kobayakawa | family |
| リンコ | Rinko | given |
| コバヤカワチャン | Kobayakawa-chan | nick |
| リンコチャン | Rinko-chan | nick |
| リンチャン | Rin-chan | nick |
| コバヤカワクン | Kobayakawa-kun | nick |
| リンコクン | Rinko-kun | nick |
| コバヤカワサン | Kobayakawa-san | nick |
| リンコサン | Rinko-san | nick |
| リンコゴメンナサイ | Rinko — I'm sorry | special |
| リンコアイシテルヨ | Rinko — I love you | special |
| リンコガイチバンダイスキ | I love Rinko the most | special |

## Nene Anegasaki

| Katakana | English | Kind |
|----------|---------|------|
| ネネ | Nene | given |
| アネガサキ | Anegasaki | family |
| ネネセンパイ | Nene-senpai | nick |
| アネガサキセンパイ | Anegasaki-senpai | nick |
| ネネチャン | Nene-chan | nick |
| アネガサキチャン | Anegasaki-chan | nick |
| ネネクン | Nene-kun | nick |
| ネネサン | Nene-san | nick |
| アネガサキサン | Anegasaki-san | nick |
| ネネゴメンナサイ | Nene — I'm sorry | special |
| ネネアイシテルヨ | Nene — I love you | special |
| ネネガイチバンダイスキ | I love Nene the most | special |

## Shared special lines

Same blob as the heroine names (`0x73FEFA` onward):

| Katakana | Romaji | English |
|----------|--------|---------|
| モウシマセンユルシテクダサイ | Mou shimasen yurushite kudasai | I won't do it again, please forgive me |
| スキダヨスキダヨスキダヨ | Suki da yo suki da yo suki da yo | I love you (×3) |

## Stock cluster (`0x7382AD`)

Not given names. Used for greetings, family, and a few personality / blood-type tokens.

| Katakana / JP | English |
|---------------|---------|
| 未設定 | Unset |
| ハイ | Yes / hai |
| ヨロシク | Nice to meet you |
| ウン | Yeah |
| イエス | Yes |
| ダイキライ | I hate it |
| イヤ | No / I don't like it |
| チガウ | That's wrong |
| イーエ | No (iie) |
| ノー | No |
| カゾク | Family |
| トモダチ | Friend |
| ユージン | Friend (yuujin) |
| チチ | Father |
| オトーサン | Dad |
| オヤジ | Old man / dad |
| ハハ | Mother |
| オフクロ | Mom (ofukuro) |
| オカーサン | Mom |
| アニ | Older brother |
| アニキ | Aniki |
| オニーサン | Onii-san |
| アネ | Older sister |
| アネキ | Aneki |
| オネーサン | Onee-san |
| オトート | Younger brother |
| イモート | Younger sister |
| ムスコ | Son |
| ムスメ | Daughter |
| エー | Type A |
| エーガタ | Type A |
| エービー | Type AB |
| エービーガタ | Type AB |
| オー | Type O |
| オーガタ | Type O |
| ジョーネツテキ | Passionate |
| オーザッパ | Sloppy |
| テンネン | Natural / airhead |
| キチョーメン | Meticulous |
| ブットンデル | Detached |
| ジブンカッテ | Selfish |
| 不明 | Unknown |
| 女性 | Female |
| 男性 | Male |
| ねむ | Sleepy |
| もう | Already / come on |
| おはよ | Morning |
| 今 | Now |
| おやす | Good night |
| 寝 | Sleep |
| 今日 | Today |
| 明日 | Tomorrow |

## Related

- Player names she can call **you**: [sayable-names-readings.md](sayable-names-readings.md)
- Overview: [sayable-names.md](sayable-names.md)
