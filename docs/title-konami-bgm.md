# Title Konami code → custom BGM

Plan for one case only: the title theme is a **standalone Siren stream** (small header, DSP-ADPCM body, loop points). Entering the Konami code on the attract/logo beat stops that cue and starts a second cue whose file we encoded from outside audio.

If the theme is a sequenced bank (`.spp` / multi-cue program, same shape as `Siren14Voice.spp`), stop. That is a different project. Do not keep going through the encoder todos.

Sequence: **Up Up Down Down Left Right Left Right B A**. Edge-triggered. Wrong press or a short timeout resets. Listen on the attract/logo beat, before the hub list owns the d-pad.

Ship path, same as other `code.bin` hooks: `deploy_name_input_en.py` → `release/name_input_code.bin`, plus a RomFS file under `Plus/Sound` in the overlay. LayeredFS after the bake hook exists. Caves stay in `.text` RX (`src/patch_input_cave_map.py`). The tail at `0x0068F800`–`0x00690000` is already occupied (message-speed, name-input, Communication Settings header).

## 0. Confirm the file is a standalone stream

- [ ] From a full RomFS (`cache/vanilla_from_rom` or the sibling dump), list `romfs/Plus/Sound/` and note sizes, extensions, and which names look like music versus `Siren14voice.bin` / `Siren14Voice.spp`.
- [ ] In Ghidra (`code.bin`, image base 0), find the title/attract state’s call that starts BGM. Record the function, the cue or path argument, and the stop call.
- [ ] Open the file that call uses. Standalone means: one header, one sample-rate / channel / loop pair, then a DSP-ADPCM body you can decode to a waveform that is the title theme.
- [ ] **Gate.** Header decodes and the body is the title theme → continue. Body is a sequence, a bank index, or silence → write that down in `docs/technical.md` and stop this plan.

## 1. Document the container

- [ ] Write the header layout next to the play-call notes: magic or size fields, codec tag, sample rate, channel count, nibble count, loop start/end, and where the ADPCM payload begins.
- [ ] Decode the vanilla title stream to wav offline and confirm it is that theme (length, loop, stereo or mono).
- [ ] Record the play-call arguments a second cue would need (path, id, volume, loop flag). Same function as the title theme, different file.

## 2. Encoder

- [ ] Add a small tool (wav in, Siren stream out) that writes the header from §1 and Nintendo DSP-ADPCM with the coefs and loop points the header expects.
- [ ] Round-trip the vanilla title file: decode → encode → byte compare, or decode both and compare samples within a tight error.
- [ ] Encode a one-second test tone with a loop. This is the first file the game should play. Keep the source wav out of git; a tiny fixture for the unit test is enough.

## 3. Second cue

- [ ] Place the tone stream in the RomFS overlay at a new path under `Plus/Sound/` (do not overwrite the title theme).
- [ ] Hook the play call so a flag chooses the new path. Flag clear → vanilla title cue. Flag set → the new file, then stop the vanilla cue first so both are not mixed.
- [ ] Prove it on Azahar with the flag forced on, before any button sequence exists. Pass: tone plays and loops on the title beat. Fail (reject, silence, crash) → the container notes are wrong; fix §1, do not start the detector.

## 4. Konami detector

- [ ] Inventory free bytes in the RX tail (`0x0068F800`–`0x00690000`) after the current caves. The detector needs its own cave. If nothing is free, stop and free or extend a pad in `.text` before writing Thumb. Never put the cave in `.rodata` (`0x006E6A38` / `0x006FBB08` prefetch-abort on hardware).
- [ ] Find the attract/logo pad poll (not the hub list). Hook it.
- [ ] State machine: ten steps, new-press only, reset on mismatch or timeout. On match, set the §3 flag and call stop + play. Matching again does not restart the stream.
- [ ] Leaving the title beat clears the flag and restores the normal cue the next screen expects.

## 5. Bake and LayeredFS

- [ ] `src/patch_title_konami_bgm.py`, applied from `tools/deploy_name_input_en.py` on vanilla `code.bin.bak` (same stack as the other caves).
- [ ] Overlay the encoded stream so Drop CIA injects it with the rest of `Plus/`. LayeredFS copy for Azahar (`romfs/Plus/Sound/…`).
- [ ] Unit test: cave bytes, sequence transitions (accept, reject, timeout), and encoder round-trip on the fixture. No `img.bin` rebuild.

## 6. Playtest

- [ ] Azahar: code on the attract beat swaps to the custom loop; a wrong press does nothing; the hub cursor still moves only from its own poll; the next screen is not stuck on the custom cue.
- [ ] Replace the test tone with the real track only after the tone loops cleanly.
- [ ] Hardware note: RX cave only. Confirm on a 3DS after Azahar, because a stream Azahar mixes can still be silent or fault on the real DSP.
