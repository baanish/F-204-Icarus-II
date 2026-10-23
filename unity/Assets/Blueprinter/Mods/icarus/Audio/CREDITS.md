# Icarus engine audio

Three seamless mono 44.1 kHz PCM24 loops, the owner's choice from the audio research (round 7, take A, "Clean, dark F110 roar: complete engine"). The recording is an F110-GE-100 afterburning turbofan in a hush house, standing in for the J79: it is not J79 audio.

| File | Role | SHA-256 |
|---|---|---|
| `turbine_a_f110_r6.wav` | Turbine whine (Turbojet.turbineAudio) | `4996c924989a6af80480abef6bed0f359dfab96f9e0ad6924cc8029cfd4b52e4` |
| `dry_a_f110_r7.wav` | Dry thrust roar (JetNozzle.thrustAudio) | `7e3cc921d8a8b1cffb19d145f1c0de5eeac7a049022c09b0978b7e47a52a22dd` |
| `afterburner_m_f110_r6.wav` | Reheat (the afterburner's source, plus +9.53 dB from ReheatGain) | `005859fcc96622ff96f9a389d23962890948266da648ce83bd17f1d8d60a4f81` |

## Source

"177th Fighter Wing gas turbine engine testing" by USAF / New Jersey Air National Guard, Master Sgt. Andrew Moseley, VIRIN 170131-Z-YH452-001, 31 January 2017, https://www.dvidshub.net/video/512154/177th-fighter-wing-gas-turbine-engine-testing . Public domain per the DVIDS item and https://www.dvidshub.net/about/copyright . The appearance of U.S. Department of War (DoW) visual information does not imply or constitute DoW endorsement.

## How each loop was made

- **Turbine:** an Earshot v0.4.0 gesture fit of the dry hold at 74-78 s, slowed 0.4537 so the fan line sits at 813 Hz (1,220 Hz at full RPM). Every tonal line is a constant partial snapped to whole cycles in a 15 s loop, over a roar rendered from earlier fits of the same recording, shaped with fixed shelves, its crest lowered by magnitude-preserving shaping and its level set by linear gain.
- **Dry roar:** the dry run at 72-82 s, low-passed at 500 Hz with a small bass shelf, its 56 Hz engine-order line ladder removed in the STFT, 250-400 Hz eased 3 dB, magnitude-preserving crest shaping and linear gain to -12 LUFS.
- **Reheat:** Earshot v0.4.0 spectral renders fitted from the recording's static reheat hold (292-304 s), with oversampled band-limited saturation (nothing above 5.5 kHz), a 30-90 Hz rasp at 700-4,000 Hz, a sub boost with slow random level movement and generated crackle transients; true peak set by linear gain to -1.2 dBTP.

No owner-supplied reference audio and no Nuclear Option stock audio enters any loop; they were measurement references only.

[Earshot](https://github.com/Leonxlnx/earshot) v0.4.0, copyright 2026 Leon Lin, MIT licence, was the synthesis tool; its output carries no Earshot code.

## Aircraft sounds

Three mono 44.1 kHz PCM24 clips, the owner's picks from the audio research's aircraft pass. Flare release, tyre roll and skid, speed-brake airflow and canopy jettison keep the Revoker's stock clips, also by the owner's choice.

| File | Role | Length, loudness, true peak | SHA-256 |
|---|---|---|---|
| `gear_fold_icarus.wav` | Gear travel (LandingGear.foldSound, all three legs, at volume 0.379) | 4.6 s, -11.8 LUFS, -1.56 dBTP | `2a30a3bcb290fdf93d27b27ee7842091b56e747501402d61e16d7f9fc4f37441` |
| `gear_latch_icarus.wav` | Gear lock (LandingGear.latchSound, at volume 0.373) | 0.85 s, -17.6 LUFS, -1.0 dBTP | `2f1751f273cb1262773bc00b50ddff845a342305aed8780a6ac301b13d7932d3` |
| `runway_scrape_icarus.wav` | Belly scrape (Aircraft.scrapeSound), seamless loop | 7.98 s, -12.6 LUFS, -1.3 dBTP | `7ae94e681c14309e8d037fd7c571b3ee63b430202e1cc66026d7d4d908209ec1` |

### Sources

All CC0 1.0 (https://creativecommons.org/publicdomain/zero/1.0/), a public-domain dedication, read from each sound's own licence link on its Freesound page. The audio used was Freesound's high-quality preview.

- "landing gear" by Ramstar757, https://freesound.org/people/Ramstar757/sounds/763119/ (gear travel)
- "Motors_Hydraulic_Handycap_Ramp" by SoundsofTheMachine, https://freesound.org/people/SoundsofTheMachine/sounds/784981/ (gear travel, gear lock)
- "metal heavy dungeon prison door unlatch open close thud rattle and hatch open close slide squeak various ext perspective on offmic +bg hostel kitchen sounds2.wav" by kyles, https://freesound.org/people/kyles/sounds/407323/ (gear travel)
- "METAL SFX & FOLEY, Metal slide, clunk and clink (door bolt).wav" by Alexbuk, https://freesound.org/people/Alexbuk/sounds/391794/ (gear lock)
- "crowbar metal drag on concrete scrape and handling.wav" by kyles, https://freesound.org/people/kyles/sounds/452587/ (scrape)
- "over the bridge Highway drive interior" by gecop, https://freesound.org/people/gecop/sounds/521767/ (scrape)

### How each clip was made

Each clip is a sum of Earshot v0.4.0 renders of fits to excerpts of those recordings, so it is fresh noise and resynthesized tones, not the recordings themselves:
- **Gear travel:** the hydraulic pump (gesture fit, 2.5-7.5 s) spinning up from 0.85x to 1x over 0.3 s, the ramp motor as mechanical travel (gesture fit, 4-9 s, -5 dB) and an uplock clunk (modal fit, 17.8 s, -8 dB). Filtered 35 Hz to 9 kHz, crest lowered by magnitude-preserving shaping, then linear gain to the donor gearfold's loudness. It lasts 4.6 s, longer than the nose leg's 4.0 s cycle, so no leg goes quiet before its lock. The game plays it at 0.379 instead of 0.3, 2.0 dB over the donor, at the owner's request.
- **Gear lock:** the ramp motor's end-stop clunk (modal fit, 10.45 s) with a steel bolt snap 6 ms in (modal fit, 5.38 s, -7 dB). Played at 0.373, which matches the donor latch1's loudness, because the file's peak reaches -1 dBTP first.
- **Belly scrape:** the crowbar drag (spectral fit, 22-30 s) over the road-tyre roar raised 1.5x, low-passed at 400 Hz and 6 dB down, as an 8 s seamless loop. A 4x oversampled soft clip above 2.5x RMS bends only its loudest grit grains (1.9% of samples, distortion 24 dB under the signal) to reach the donor's loudness, since the game drives its volume to 1 in code.

No owner-supplied reference audio and no Nuclear Option stock audio enters any clip.
