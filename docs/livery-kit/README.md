# F-204 Icarus II livery kit

Everything you need to paint your own livery for the F-204 Icarus II mod for Nuclear Option, and to install it in the game. A livery is one picture, 4096 by 4096 pixels, that the game wraps around the jet. This kit gives you the jet's paint model to paint on, the seven liveries the mod ships as examples, and the guides for painting in a 2D image editor.

Status of this guide: the kit's files are checked against the mod's own maps and model, and a livery built with these steps was installed and shown in the game on both sides. Steps not yet tried in the game say **to be proven**.

## What is in the kit

| File | What it is |
|---|---|
| `model/icarus_paint_model.blend` | The jet's outer skin as one object, ready to paint on in Blender. It shows the first example livery. |
| `model/icarus_paint_model.fbx` | The same model for other 3D paint programs, such as Substance Painter. |
| `examples/Icarus_livery_1.png` to `_7.png` | The seven shipped liveries, faction roundels included (list below). |
| `examples/Icarus_livery_4_m.png`, `_7_m.png` | The metal maps of the two Bare Metal liveries. They show how the shipped Bare Metal works; your livery cannot use one (see [What the game does with your paint](#what-the-game-does-with-your-paint)). |
| `template/layers/Icarus_livery_<n>_base.png` | Each shipped livery's colours with no markings and no panel lines: a starting point to recolour. |
| `template/layers/Icarus_livery_<n>_markings.png` | That livery's numbers, lettering and roundels on a transparent layer. |
| `template/Icarus_panel_lines.png` | The dark lines in the panel joints and around the rivets, on a transparent layer. The shipped liveries have this layer on top. |
| `template/Icarus_uv_layout.png`, `.svg` | The outline of every piece of the picture: thick lines are piece edges, thin lines the model's faces. |
| `template/Icarus_part_map.png` | Each part of the jet in its own flat colour, for selecting a part in an image editor. |
| `template/Icarus_part_labels.png` | The part names, on a transparent layer to put over the part map. |
| `template/Icarus_parts.csv` | Every part, its colour in the part map, and its plain name. |
| `maps/Icarus_skin_n.png`, `_m.png`, `_ao.png` | The jet's shared surface maps (bumps, metal and shine, shadowing), for previewing in a 3D paint program. The game supplies these itself; you never install them. |
| `install/IcarusLiveryBuilder.cs` | Builds your picture into a livery the game can load (see [Install your livery](#install-your-livery)). |
| `install/meta.json` | The livery's label file, set up for the Icarus. |

The example liveries:

| File | Livery | Side |
|---|---|---|
| `Icarus_livery_1.png` | PALA Navy | PALA |
| `Icarus_livery_2.png` | PALA Black | PALA |
| `Icarus_livery_3.png` | PALA Desert | PALA |
| `Icarus_livery_4.png` | PALA Bare Metal | PALA |
| `Icarus_livery_5.png` | BDF Matte Gray | BDF |
| `Icarus_livery_6.png` | BDF Gray Camo | BDF |
| `Icarus_livery_7.png` | BDF Bare Metal | BDF |

## Paint on the 3D model

This is the recommended way. You paint straight onto the jet and the program writes into the flat picture for you, so you never have to work out which piece of the picture is which part of the jet. Blender is free and does this; these steps use it.

1. Unzip the kit and keep its folders together: the model finds its pictures through them.
2. Pick a starting picture and copy it into `examples/` under a new name, for example `my_livery.png`. `examples/Icarus_livery_5.png` (BDF Matte Gray) is a plain grey jet with markings. `template/layers/Icarus_livery_5_base.png` is the same grey with no markings at all.
3. Open `model/icarus_paint_model.blend` in Blender. The whole skin is one object, `Icarus_skin`, already selected and active, so the brush reaches every part of the jet. Switch to the **Texture Paint** workspace (tab at the top). If you clicked elsewhere first and the jet no longer shows an orange outline, click it once in the viewport before switching.
4. In the image editor on the left, choose **Image > Open** and open your `my_livery.png`.
5. In the panel on the right, open the **Tool** tab, find **Texture Slots**, set **Mode** to **Single Image** and pick `my_livery.png`. You now paint into your picture and see it on the jet.
6. Paint. Turn the view with the middle mouse button; set brush colour, size and strength in the tool settings at the top.
7. Save with **Image > Save** in the image editor (Alt+S). Blender does not save painted pictures when you save the .blend file, so save the image itself.

Substance Painter and other 3D paint programs open `model/icarus_paint_model.fbx`. Set the document size to 4096 and export only the base colour as a PNG.

## Paint in a 2D image editor

If you would rather draw flat, open your starting picture in an image editor that has layers (GIMP and Krita are free, Photoshop works too) and add the template images as layers above it:

- **Select a part.** Add `Icarus_part_map.png` as a layer, use the magic wand on it with "contiguous" turned off, and one click selects every piece of that part, for example all of the left wing. Hide the part map, then fill or paint inside the selection on your own layer. The part colours reach 16 pixels past each piece's edge, the same way the shipped paint does, so a filled part shows no seam at its edges.
- **Find a part.** `Icarus_part_labels.png` names the larger pieces. `Icarus_uv_layout.png` shows every piece's outline.
- **Ignore the thin strips.** The many thin strips are the edges of the wings and tail, the gear doors, the pylons and the 32 small pieces of the engine nozzle. Together they hold about a tenth of the picture. Fill the whole picture with your base colour first and they take it. The fuselage sides, wings, fin and tailplane are where a livery shows.
- **Rebuild a shipped livery.** Stack `layers/Icarus_livery_<n>_base.png`, then `layers/Icarus_livery_<n>_markings.png`, then `Icarus_panel_lines.png` (normal blending), and you get that shipped livery back, within one colour step on almost every pixel. The two Bare Metal liveries are the exception: their shipped panel joints are shaded a little lighter than painted ones (22% darker at a joint where paint is 30% darker), so rebuilt with this layer their joints come out slightly darker than shipped. Recolour the base layer to make a new scheme with the same markings.
- **Recolouring leaves a fringe.** The markings layer's edge pixels were blended with the original base colour when the shipped livery was made, and the layer keeps them fully opaque. Over a base close to the original you will not see it; over a very different one (a white base under the grey jet's markings, say) each marking keeps a thin outline of the old colour, about a pixel wide. Paint over or erase that outline on the markings layer in your new colour, or start from the example picture itself and paint your new colours up to the markings.

Save the result as a PNG, 4096 by 4096 pixels, without transparency.

## What the game does with your paint

Your picture is only the colour of the paint. The game adds everything else from the jet's own maps:

- **Panel joints and rivets** are shaped by the jet's bump map, on every livery, so they show through your paint as shading. The dark lines in the joints are painted in the shipped liveries. Add `template/Icarus_panel_lines.png` on top of your picture if you want them; leave it off for a cleaner jet.
- **Shine and metal** come from the jet's shared metal map: your paint is painted metal with a satin shine everywhere, except the bare metal ring at the tail end of the fuselage and the engine nozzle, which are unpainted metal on every livery. Paint those areas a metal grey, since any colour you put there looks like tinted metal.
- **Bare Metal**: the polished, mirror-like aluminium of the two shipped Bare Metal liveries comes from a metal map only those two liveries use. The mod picks it by recognising their exact pictures, so a livery of yours always gets the painted finish: a silver livery looks like silver paint, not polished metal.
- **Damage**: soot, scorches and holes come from the jet's damage maps and appear over your paint as the parts are hit. You paint nothing for damage.
- **Mirrored parts**: the leading-edge flaps, speed brakes, intake ducts, nose and main gear doors, and wing pylons each share one piece of the picture between the left and right side (`Icarus_parts.csv` lists them). Whatever you paint there shows on both sides, and text there reads backwards on the right side. Wings, flaps, ailerons, fuselage and fin have separate left and right pieces, so numbers and lettering read correctly on both sides there.
- **Roundels**: the game adds no national markings. Keep the roundels from the markings layer, or paint your own.
- **Tip tanks**: both tanks wear your picture, but only two small spots of it, about 3 pixels across, on the left wing's piece (`wing_skin_L`): their upper halves take the colour round pixel (479, 2035) and their lower halves the colour round pixel (1294, 2612), counting from the picture's top-left corner. These are points on the left wing's upper and lower skin, so a plain wing gives the tanks its colour. To give the tanks another colour, paint a patch a few pixels wide round each spot; a marking or panel line across a spot shows on the tanks as a smear of its colour.
- **Other stores** take their colour from your livery's main colours, which the builder picks from your picture.

## Install your livery

The game loads a player's livery from a folder in its save data, built by the game developer's own livery project for Unity. These steps use that project with the kit's builder, which labels the livery for the Icarus and makes sure the build writes the catalog the game reads. The build, the folder and the livery list were tried in the game through the builder's command line (below). The Inspector steps run the same code but were not clicked through.

You need:

- Unity Hub and the Unity editor version the livery project asks for when you open it (2022.3.62f2 when this was written).
- The livery project: download it from https://github.com/Shockfront-Studios/Nuclear-Option-Mods (**Code > Download ZIP**) and unzip it.

Then:

1. Open the project in Unity Hub (**Add > Add project from disk**, pick the unzipped folder) and wait for it to finish importing.
2. Copy `install/IcarusLiveryBuilder.cs` from this kit into the project's `Assets/Scripts/Editor/` folder. Unity compiles it and adds a menu item.
3. Drag your `my_livery.png` into the project's `Assets` folder in Unity's Project window. Click it, and in the Inspector set **Max Size** to **4096** and press **Apply**. Unity's default of 2048 would halve your livery's detail.
4. Choose **Nuclear Option > Create Icarus Livery Builder** and save the builder asset in `Assets`.
5. Click the builder and fill it in, in the Inspector:
   - **Bundle Name**: a folder name for your livery, in lower case letters, digits and underscores, for example `my_icarus_livery`.
   - **Copy To App Data**: ticked.
   - **Texture**: your `my_livery.png`.
   - **Glossiness**: 0. A higher value makes the whole jet shinier, paint and all.
   - **Display Name**: the name the game's livery list shows.
   - **Faction**: empty to offer the livery on both sides, `Primeva` for PALA only, or `Boscali` for BDF only.
   - **Aircraft**: leave it; the Icarus builder ignores it.
6. Press **Build**. The livery is written to the project's `Bundles/my_icarus_livery/` folder and copied to the game's skins folder:
   `%USERPROFILE%\AppData\LocalLow\Shockfront\NuclearOption\Skins\my_icarus_livery\`
   It holds four files: `catalog_1.json`, `catalog_1.hash`, `meta.json` and `my_icarus_livery_assets_all.bundle`.
7. Start the game, pick the Icarus and open its livery list. Your livery is listed as its display name followed by "(app data)", on the sides its faction allows.

To build without opening the editor, run Unity from a command prompt, as one line:

```text
"<Unity editor folder>\Unity.exe" -batchmode -quit -projectPath "<livery project folder>" -executeMethod IcarusLiveryBuilder.BuildFromCommandLine -icarusTexture "<your png>" -icarusBundle my_icarus_livery -icarusName "My Icarus livery"
```

Add `-icarusFaction Primeva` or `-icarusFaction Boscali` for one side only. The command imports your picture at 4096 itself and copies the folder to the skins folder, as **Build** does.

Use the kit's builder, not the project's own Create Livery Builder. That one only knows the game's own aircraft, so its `meta.json` never matches the Icarus. And in a test on a fresh copy of the project, its build wrote no `catalog_1.json`, without which the game cannot load the livery.

To give your livery to a friend, zip the folder from step 6. They unzip it into the same `Skins` folder on their PC.

In multiplayer, other players see your livery only if they have the same folder installed, or the same Workshop livery subscribed. Everyone else sees your side's first livery on your jet: PALA Navy for Primeva, BDF Matte Gray for Boscali. **To be proven** in game.

## Share it on the Steam Workshop

From version 0.4.0 the Icarus mod gives the jet a Workshop tag, `F-204 Icarus II`, which the game's Workshop uploader needs before it accepts a livery for it. The tag is set in the game: the mod's log shows it at load. The steps below follow the game's code and have not yet been tried: **to be proven** in game.

1. Build your livery as in [Install your livery](#install-your-livery), so its folder is in the game's `Skins` folder.
2. Start the game with the Icarus mod installed and open the Workshop menu's upload page.
3. Choose **Aircraft Livery** as the type and press **Next**.
4. Pick your livery's folder name, for example `my_icarus_livery`, and press **Next**.
5. Fill in the details page: a title, a description and a preview image (a new item needs all three), and whether the item is public. Tick **Mod Required**, so Workshop visitors see that the livery needs a mod. The page shows the tags the livery gets: `F-204 Icarus II`, plus the side if you set a faction.
6. Press **Create New**. This uploads the livery to the Steam Workshop under your account.

To use a Workshop livery, a player installs the Icarus mod and subscribes to the livery. It then appears in the Icarus's livery list with "(workshop)" after its name.

A player without the Icarus mod still sees the livery in the game's Workshop browser under Aircraft Livery, with its tags. If they subscribe, it downloads but appears in no aircraft's livery list, because its `meta.json` names the Icarus and no other aircraft matches it. It never shows on a stock aircraft.
## For modders: how the game finds a livery

- On the aircraft menu, the game lists the aircraft's own liveries, then every folder in `Skins` and every subscribed Workshop livery whose `meta.json` matches the aircraft (`LoadoutSelector.GetLiveryOptions`).
- `meta.json` matches when its `AircraftKey` equals the aircraft's key, `baanish_icarus` for the Icarus. Without an `AircraftKey`, `Aircraft` must equal the aircraft's Workshop tag or its name (`LiveryMetaData.CheckAircraft`). A non-empty `Faction` limits the livery to that side.
- The Workshop uploader takes the tag of the aircraft that `meta.json` matches and sends it to Steam with `Aircraft Livery` and the faction (`AircraftLiveryMod.TryGetItem`). The Icarus plugin sets the Icarus's tag once the jet is loaded (`LiveryWorkshopTag`). Matching a subscribed livery uses `meta.json`, never the tag.
- The folder's `catalog_1.json` is an Addressables catalog whose `LiveryData` entry carries the label `Skin`. Its bundle path starts with `{NuclearOption.AddressablePaths.AppDataSkinPath}`, which the game fills in with its `Skins` folder (`ModLoader.GetAddressableKeyFullLoad`, `AppDataSkins`).
- A `LiveryData` holds the colour picture, a glossiness and up to five main colours. The game puts the picture and glossiness on every skin material of the aircraft (`UnitPart.SetLivery`).
- The aircraft's chosen livery travels to other players as a key naming the folder. A player without that folder gets the aircraft's first livery for its side (`LiveryBehaviour.Load`, `AircraftParameters.GetFirstLiveryForFaction`); the Icarus lists its liveries by number, so that is PALA Navy for Primeva and BDF Matte Gray for Boscali.

## Licence

See `LICENSE.txt`. The faction roundels in the examples and markings layers are the game's own art; everything else in the kit is under the MIT licence.
