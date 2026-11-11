# Using Nemo

Nemo for a Fujitsu Lifebook AH531 running Windows 11: an Intel Pentium B960
(Sandy Bridge, two threads, no AVX), 8 GB of DDR3-1333 in dual channel, and
Intel HD Graphics on Intel's final 2016 driver.

## Using Nemo

After installing, open **Nemo** from the Start menu or the desktop shortcut
(on NemoIso: the applications menu). The window has four tabs.

**The prompt window.** On NemoIso, Nemo opens by itself when the desktop
starts, at a window with a pulsing orb and one box: type what you would like
and press **Send** (or Ctrl+Enter). A thing to build becomes a new project,
and Nemo drafts its brief; a story is kept in the Story list. **Open the
workshop** goes to the tabs below. `nemo gui --prompt` opens it anywhere.
**Speak** (pressed again to stop) listens through the laptop's microphone, offline, and puts what it heard in the box: check it, then Send.

**Your work on the stick.** On NemoIso started from a USB stick, projects and
stories are kept in a `NemoData` folder on the stick: saved every two
minutes, at shutdown, and when you press **Save to stick**, and put back at
the next start. Files you delete go to `NemoData/.removed`, not away. The
folder can be opened from Windows too. Started from a DVD or in an emulator
there is no stick, and nothing is kept.

**Brief** is where a project starts. Fill in what it does, the power
source, the enclosure size and the parts, or write a sentence under "What it
does" and choose **Draft it with Nemo** to have the model fill in the rest.
Picking a part shows what to watch out for with it -- the RC522's antenna
clearance, the MAX98357A's shutdown pin. The line beside **Save brief** says
what is still missing.

**Story** lists the stories asked for in the prompt window, newest first,
with what was asked. A story asked for there is written straight away if a
model is loaded; otherwise choose it here and press **Write it**. The
Library's employees write it: the **Writer** plans a title and the chapters (about
three for a short story, ten for a novel, or as many as you ask for) and
the **Editor** checks the plan; the **Writer** then writes one chapter at a
time, shown only that chapter's line so it does not wander into the next,
and checks its spelling, correcting only slips that cannot change a meaning
(a doubled word, two swapped letters, a doubled letter); the **Editor**
reviews every chapter (empty, far too short or long, talking to the reader,
repeating the last chapter, full of spelling or grammar the Writer could not
settle) and sends it back once with the reason. **Open its folder**
shows `story.md` (the whole story), `outline.md`, each chapter, and
`work.jsonl`, the log of who did what. From the command line: `nemo story
new "<what it is>"`, `nemo story list`, `nemo story write <name>`.

**Paint a cover** has the **Artist** paint the chosen story's cover,
`cover.png`, from its title and what you asked for, with a local image model
(stable-diffusion.cpp and SD-Turbo, Stability AI's non-commercial community
licence). Nothing leaves the laptop. It takes about 11 minutes here
(measured), needs about 2.9 GB free, so unload the language model first
(Model: Off), and **Stop** ends it. `nemo story cover <name>` does the same.
NemoWin only for now: the files are in `C:\Nemo\artist`, and NemoIso's
image does not carry them yet.

**Pictures.** Nemo draws the housing, and invents nothing in it.

- **The housing, drawn from its STL.** On the Files tab, **View the housing**
  (or `nemo render`) draws the real enclosure: four views (isometric, top,
  front, right) with its measured size and whether it fits the brief's
  envelope. It draws the file rather than imagining a box, so a speaker hole
  on the wrong face shows up before anything is printed, and the same file
  always gives the same image. It needs numpy (the optional `cad` extra). A
  detailed housing takes seconds on a fast machine and may take tens of
  seconds on this laptop (measured only under emulation); the window stays
  usable while it draws.

- **The Artist's concepts, before the case is modelled.** The **Concept**
  step draws two ways the case could be: **A**, what Nemo would build unasked
  (square corners, the cable opening in the left wall), and **B**, the parts
  arranged another way that keeps the same rules (rounded corners, the
  opening in the front wall). Each is built in CadQuery and drawn from the
  model, with a floor plan naming the parts, so what you pick is what gets
  made. **Choose a concept...** shows both; pick one, change its corners or
  which wall the cable opening is in, and say anything about where the parts
  go. The Designer then builds that, and the Enclosure step will not start
  until you have chosen. `nemo concept show` and `nemo concept choose B
  --corners square --changes "..."` do the same.

The enclosure concepts are drawn from geometry, never by an image model: a
painted box could be one the Designer cannot build. Only story covers are
painted (above). Measured here before that was decided: one 512-pixel cover
took 27 minutes with the image model's own decoder and 11 with the tiny
TAESD decoder, which is what Nemo uses.

**Parts.** The library has 26 parts: the RFID player and pendant parts,
plus common sensors (BME280, MPU-6050, VL53L0X, DS18B20), an OLED display,
a motor driver (DRV8833), addressable LEDs, a servo, a relay module, the
Raspberry Pi Pico, an ESP32-C3 board, an ESP32-S3 board that can read a USB
device as host, a USB socket, LiPo cells of 500, 1000 and 2000 mAh,
a boost converter and a level shifter. Each part says where its figures came from:
a module's figures are often a vendor's, not the chip maker's, so check
the ones a design depends on against the datasheet.

If a part you need is missing, choose **New part...** beside the search box
(or `nemo part add`). It asks for what the checks actually use -- voltages,
current, size -- with the units beside each box, and it requires a name, a
category and *where the figures came from*, because everything downstream
trusts them. Your parts are saved in your own parts folder and never change
the bundled library; a part with the same reference as a bundled one replaces
it, which is how you correct a figure, and Nemo asks you to confirm that.
Three things to know:

- **Motor drivers and relays.** The DRV8833's current is a *stand-in* for the
  motor you attach, not the chip's own draw. Set it to your motor's real
  running and stall current or the power check will be wrong. The relay
  module's switched side can carry mains; treat that as a job for a rated
  enclosure and a qualified person, not this pipeline.
- **The boost converter** is in the library, but Nemo's power suggestions do
  not yet plan around it. Add it by hand and account for the 5 V rail it makes.
- **YAML and yes/no words.** In any harness or parts file, write pin names
  NO, ON, OFF, YES, Y and N in quotes ("NO"). Unquoted, YAML reads them as
  true/false. Nemo now says so instead of failing with a confusing message.

**Suggest power**, beside the power source, works out what your parts draw
and lists the supplies that suit them: USB chargers of each size and, if
your parts library has a LiPo cell and a protected charger, a battery. Each
is marked Recommended, Enough, Too small or Not suitable, with the reason.
Choosing one fills in the power source, supply rating and rails, and adds
the battery parts if needed; nothing is saved until you choose **Save
brief**. A battery-powered design is never switched to mains power for you:
if no battery in the library can do the job, Nemo says so and says why.

**No power needed / No parts needed**, on the Brief tab, are for things that need neither: a holder, a case, a passive prop. The brief stops asking for them, the steps that need them say they are not needed instead of failing, and no model is loaded for them.

**The Researcher** looks up online what the Inspector finds missing (an RFID reader the parts don't include, a part name the library doesn't know) in Mouser's parts catalogue, and the Inspector offers each find as a fix: **Open the link** shows its datasheet. Only the missing thing is sent, never your brief. It needs a free Mouser Search API key: **Researcher key** on the left. Add a part it finds with **Add a part**, from its datasheet; Nemo puts nothing found online into the library by itself.

**Nemo's departments.** The employees work in twelve departments, each with its own team: the **Library** (stories and language: Researcher, Writer, Artist, Linguist, Editor), the **Art Studio** (pictures and 3D models to print: Writer, Artist, Designer, Editor, Clerk, Foreman, Timekeeper), the **Workshop** (hardware: Researcher, Writer, Designer, Inspector) and the **Computer Lab** (code: Writer, Designer, Coder, Tester, Technician, Reverse Engineer) the **Storeroom** (the parts you have to hand: Storekeeper, Writer, Researcher), the **Theatre** (Projectionist for video, Streamer for websites, Photo Curator for pictures, Writer), **Gaming** (an Attendant, an emulator for each console, Writer), the **Music Room** (Player, DJ, Writer), **Audio** (Narrator, Recorder, Sound Engineer, Librarian, Writer), the **Test Bench** (Flasher, Serial Monitor, Writer), the **Print Shop** (Slicer, Writer), the **Film Studio** (Director, Storyboard Artist, Narrator, Editor, Writer), **Home** (Surveyor, Gatekeeper, Device Keeper, Writer), **Communications** (Browser, Postman, Social, Writer), **Science** (Calculator, Mathematician, Physicist, Statistician, Bookkeeper, Writer) and the **Doctors** (what has gone wrong: GP, Machine, Model, Design and Stick Specialists, Records Clerk, Nurse, Writer). Five more jobs are on the roster to save the model work (Timekeeper, Foreman, Archivist, Clerk, Technician). Not all of them are built yet: today the Library writes stories and covers, and the steps below are done by the Workshop, with the concept from the Art Studio and the firmware from the Computer Lab.

**Storeroom**, on the left, opens **Nemo Video**: a 90s video store with an aisle each for BOOKS (your stories), GAMES, VIDEOS, PICTURES and PARTS. Click a case to read, play, play here or cast, show, or see a part's details. Before the parts step, Nemo notes which of the brief's parts are already on your shelves, how many and where, and which you still need; and before the Researcher searches Mouser for something missing, it looks on your shelves first. **Parts catalogue...** in that window is your catalogue of the parts you have to hand: what, how many, where they are kept, and notes. **Add** puts parts on the shelves (adding one already there adds to its count), **Take** takes some off when you use them, **Remove** takes an item off the list. A part named exactly as in the parts library is linked to it; choose the **Library part** to link one that is not, or press **Suggest**: the Researcher puts the likeliest library part in the box (by its part number, such as BME280, then its name) and says why, and **Link** links it. Nothing is linked until you press Link. From a terminal: `nemo store suggest` (every unlinked item) and `nemo store link "<item>" --part <ref>`. From a terminal: `nemo store add "Red LED 5 mm" --qty 10 --where "drawer 3"`, `nemo store take "Red LED 5 mm" --qty 2`, `nemo store`. It is kept in `~/nemo-storeroom/stock.yaml` (on the stick, NemoData/nemo-storeroom). It does not change the parts library, and no step uses it yet. **Back up Nemo...**, in the same window, makes a backup of your work: choose a folder (by default `~/nemo-backups`) and Nemo writes one zip of your projects, stories, Storeroom, the parts and datasheets you added, and your settings, with a list of every file's checksum. It never holds the program or models (reinstall them), the Researcher's key, or the admin and safety settings. From a terminal: `nemo backup`, `nemo backup list`, and `nemo backup check <file.zip>` to see that a backup is whole. To put one back, for now, unzip it by hand.

**The Linguist** hears and speaks. **Speak**, in the prompt window, turns what you say into text (offline). Nemo also says aloud when a long job ends (a step run, a brief drafted, a story written, a model loaded), and **Read aloud** in the prompt window reads its last words. It uses the voices already on the computer, a British one first: on Windows, Windows' own (Microsoft Hazel on the Fujitsu); on NemoIso, espeak-ng. The **Voice** switch at the top of the window turns it off. No language model is used, and nothing is sent anywhere.

**Is everyone equipped?** `nemo staff` lists every employee's tools on this computer, ready or missing; `nemo staff library` shows one department. In the Library: `nemo lookup <words>` (the Researcher looks it up on Wikipedia, sending only those words; `--story <name>` keeps what it finds with the story), `nemo times` (the Timekeeper: how fast the model reads and writes, from its own logs), `nemo archive` (the Archivist: answers from steps that passed, reused when exactly the same question comes again; `nemo archive clear` forgets them), and `nemo queue` (the Foreman: `nemo queue add <project> [steps]`, `nemo queue story <name>`, then `nemo queue run`, perhaps before bed; it runs them in the order that loads the models fewest times).

**The Workshop's Clerk.** What you choose from the Brief tab's lists (the microcontroller, the parts, the power supply, its rating and the inside size) stays as you chose it when you press **Draft it with Nemo**: the model is told those are decided and to leave them out, so it writes less, and Nemo puts your choices back whatever it wrote. The draft's notes say what was kept. Leave a list empty to let the model choose. `nemo queue --department workshop` and `nemo times --department workshop` show the Workshop's own queue and timings.

**The Computer Lab.** `nemo test` (the Tester) compiles a project's firmware as it is now, after you have edited it by hand say, without the model, and reports the compiler's warnings and how much RAM and flash it uses. **Load ahead**, at the top of the window (the Technician), starts loading the model the next step needs as soon as a step passes, while you read the results, so Run does not wait; it never loads one that would not fit in memory. `nemo ahead` says what it would load and why.

**Art Studio**, on the left, makes a model to 3D print from a kit of shapes: box, rounded box, cylinder, cone, sphere, plate and text. Add each shape with its sizes in mm and where it sits (x y z of the middle of its foot), as an addition or a cut, then **Build and check**. The Designer builds it (about half a minute), and the Editor checks it will print: a closed mesh, no wall under 1.2 mm, it fits the printer, and its size is what the shapes add up to. The model and its picture are kept in `~/nemo-models/<name>`. It makes plain solids (stands, plaques, holders, simple replicas), not faces or figures. **From a list...** is quicker: choose a plaque, an open box, a round pot, a tag or a stand, fill in its sizes, and the Clerk makes the shapes for you (it remembers your last choices). Words on a plaque or tag stand out from it and must be at least 17 mm tall, or their strokes are too thin to print. **Queue it** adds the model to the Foreman's queue to build later with other jobs (`nemo queue run`); **Card...** gives the model a title and a line and writes its card: what it was made from, its size, whether the Editor passed it, and any Print Shop slices. From a terminal: `nemo model shapes`, `nemo model build <shapes.json>`, `nemo model kinds`, `nemo model make pot "Pen pot" diameter=70`, `nemo model card <name> --title "..."`, `nemo queue model <shapes.json>`, `nemo queue print <model>`, `nemo times --department art_studio` (how long builds take here), `nemo model`.

**Theatre**, on the left, plays your videos and pictures: put them on the Storeroom's `videos` and `pictures` shelves (folders in `~/nemo-storeroom`); story covers and concept drawings are there too. **Play here** opens one on this computer (VLC for videos). **Find Chromecasts**, then **Cast**, sends it to a Chromecast on the same network, with Pause and Stop; it must be an MP4, M4V or WebM video or a common picture file, as Nemo does not convert video. Windows may ask once whether Python may accept connections: say yes on your home network. **Open Chrome**, with a web address, is for websites: cast them with Chrome's own menu, Cast. Before casting a video, the Projectionist looks inside it and says if the Chromecast may not play it: some MP4s are H.265, which only a Chromecast Ultra or a Google TV model plays, and Dolby sound may come out silent. It still casts; if the Chromecast cannot play it, Nemo lets it go. `nemo theatre check <name>` shows what is inside a video. From a terminal: `nemo theatre`, `nemo theatre play <name>`, `nemo theatre cast <name>`, `nemo theatre devices`, `nemo theatre stream <address>`.

**Gaming**, on the left, plays your own retro games with RetroArch, one emulator per console: NES, SNES, Mega Drive, Master System, Game Boy and Game Boy Color, Game Boy Advance and Atari 2600. Put each game file in its console's folder on the Storeroom's `games` shelf (**Open the games shelf**), choose it and press **Play**; Esc quits the game. Nemo never downloads games. On NemoIso the Mega Drive, Master System and Atari 2600 emulators are not available yet. From a terminal: `nemo games`, `nemo games play <name>`, `nemo games emulators`. Your game saves (in-game saves and save states) are kept in the Storeroom's `game-saves` folder, so backups and the stick keep them; saves made before are copied there the first time a game starts from Nemo. If a game file is on the wrong console's shelf, or has no header for that console, Nemo says so when it lists or plays it (it cannot tell for Atari 2600 games). Backups leave the videos and games shelves out, but keep the saves.

**Doctors**, on the left, looks at what has gone wrong and advises: the machine, the models (one not on disk, a model that has stopped, too little memory to load one), failed steps in your projects, saving to the stick, the Storeroom, and whether you have a backup. Each finding says what was seen, what it means (or that it is not known: Nemo does not guess), and what to do. Looking changes nothing. Where the **Nurse** can apply a remedy (clear the record of a model that has stopped, set an unreadable Storeroom catalogue aside, make a backup, or give the model longer after a step ran out of time), the finding has an **Ask the Nurse** button: it shows exactly what would change, and does it only if you say yes, one remedy at a time. A copy of every file it changes is kept: **Undo the last treatment** puts them back, unless you have changed them since. The Nurse can never touch your keys or the admin and safety settings. **Case notes** lists past visits and treatments. From a terminal: `nemo clinic`, `nemo clinic treat <number>`, `nemo clinic undo`, `nemo clinic treatments` and `nemo clinic notes`. **Write a report** (or `nemo clinic report`) has the Doctors' Writer write up the case in `~/.nemo/clinic/reports`, with your project names and home folder left out, so you can show it to someone.

**Music Room**, on the left, plays the music on the Storeroom's `music` shelf here (VLC), or casts it to a Chromecast one track after another, and keeps your playlists. Each track's title, artist, album and number come from its own tags (MP3, M4A, FLAC, Ogg and Opus); a file with no tags is named from its folders, Artist/Album/track. Backups keep your playlists, though not the music. From a terminal: `nemo music`, `nemo music play <names>`, `nemo music cast <names> [--to <Chromecast>]`, `nemo music save <playlist> <names>`.

**Audio**, on the left, has its own shelf of audiobooks, podcasts and recordings, and remembers where you left each one. The Narrator reads one of your stories aloud into a chapter-by-chapter audiobook; the Recorder records from the microphone; the Sound Engineer readies sounds for a project's DFPlayer sound board as numbered folders to copy onto its SD card, saying what will not play (that naming is not yet tried on a real module). From a terminal: `nemo audio`, `nemo audio narrate <story>`, `nemo audio card <name> <sounds...>`.

**The firmware guide.** `nemo guide` has the Computer Lab's Writer write the open project's `firmware/GUIDE.md`: which pin of the board goes to which part's pin (the same table the firmware's own pin names come from), the I2C and SPI buses, what the firmware does, and how to build it, put it on the board and listen to it. Where Nemo's code did not write the firmware, the guide lists what the file holds and does not guess what it does.

**Test Bench**, on the left, is for the board on your desk: plug it in, choose its port, **Flash it** to put the open project's firmware on it, and **Listen 10 s** to see what it prints; a crash or a brown-out is named. Each run is logged beside the project. From a terminal: `nemo bench ports`, `nemo bench flash [--port COM5]`, `nemo bench listen [--seconds 10]`. Not yet tried with a real board.

**Film Studio**, on the left, makes films for the Theatre. Choose one of your stories and press **Make the film**: the Director splits it into scenes, each is read aloud by Nemo's voice over a picture with a slow zoom, between a title card and credits, with subtitles beside it. Tick **Paint the pictures** to have the Artist paint one for each scene (about 11 minutes a picture on this laptop); otherwise the story's cover is used. **Plan** shows the scenes first, and writes the plan to a file you can change. Below, choose pictures and press **Slideshow of these**, or choose videos and press **Join these**. Films go on the videos shelf, made so every Chromecast plays them. NemoDoc fetches ffmpeg for it (`-SkipFilm` leaves it). From a terminal: `nemo film list`, `nemo film plan <story>`, `nemo film make <story> [--quick]`, `nemo film slideshow <name> <pictures...> --music <tracks>`, `nemo film join <name> holiday.mp4@5-20 other.mp4`.

**Home**, on the left, lists the devices on your home network: **Look around** asks the network who is there, the way finding a Chromecast does, and reads the address list the computer already keeps; Nemo never connects to a device, opens its pages or logs in. Every device starts as **See only**. Choose one and press **Use** to let Nemo talk to it (cast to it, or read a board's status), or **Hide** to take it off the list; every change is logged. **Casting now needs Use**: before the Theatre or the Music Room can cast to your Chromecast, set it to Use here (or `nemo home allow "Family Room TV" use`). The boards you flashed from the Test Bench are listed too. **Write the list** puts a list of your devices in the Storeroom. From a terminal: `nemo home survey`, `nemo home`, `nemo home allow "<device>" use|see|hidden`, `nemo home changes`, `nemo home boards`, `nemo home write`.

**Communications**, on the left, keeps your sites and contacts and helps you write: choose a site and **Open** it in your browser; write a message, then **Open in my mail program** (it opens with the message in it, and you press Send), **Make it a letter** (laid out with the date, greeting and sign-off, ready to print) or **Copy for a post** (paste it on your social site yourself). **Check spelling** uses the Writer's British spelling. Nemo never sends, posts or logs in for you, and keeps no passwords. From a terminal: `nemo comms bookmark <name> <address>`, `nemo comms open <name>`, `nemo comms contact <name> --email <address>`, `nemo comms email <name> --subject ... --body ... --send`, `nemo comms letter <name> --body ...`.

**Science**, on the left, works things out and shows how: **Convert units** (type `10 inch`, and `mm` in the small box), **Solve** (`x^2-5x+6=0`), **Simplify**, **Factor**, **Expand**, **Differentiate**, **Integrate**, **Evaluate**, a **Physics formula** (choose Ohm's law and type `I=20 mA R=220 ohm`), or **Statistics** (numbers with spaces between). Every answer is kept as a worked sheet in the Storeroom's `science` folder. **Save the numbers as a spreadsheet** writes an Excel file with a total and an average that work in Excel; **Open a spreadsheet** shows what is in one. From a terminal: `nemo science convert "10 inch" mm`, `nemo science solve "x^2-5x+6=0"`, `nemo science formula ohm "I=20 mA" "R=220 ohm"`, `nemo science formulas`, `nemo science stats 20.1 20.3 20.9 --sheet readings.xlsx`, `nemo science read file.xlsx`.

**When Nemo starts**, its glowing cog fills the screen with the prompt in the middle. Tell it what you want and it answers with the department that does it: that department's card, the words that chose it, and **Go there** (or **Somewhere else** to pick another, or **Back**).

**Print Shop**, on the left, slices a model from the Art Studio or a Workshop enclosure for an Anycubic Kobra 3 with OrcaSlicer (NemoDoc fetches it; `-SkipPrint` leaves it): choose the model, the quality and the filament, and **Slice it**. The G-code goes in the model's `print` folder with a card saying how long it will take and how much filament it will use (OrcaSlicer's estimate). Nemo never sends a print: copy the G-code to the printer's USB stick, or open it in Anycubic's app. From a terminal: `nemo print`, `nemo print slice <model> [--quality 0.16mm] [--filament "Anycubic PETG"]`. Windows only for now.

**Nemo's employees.** Each step belongs to one: the **Writer** (the brief: it checks the spelling, offering each correction as a fix, and before the Designer starts writes `assignment.md`, the brief as a clear job, saying what is unclear, such as a done-when that is not a test), the **Designer** (parts, schematic, wiring, enclosure), the **Artist** (the concepts of the case, and story covers), the **Coder** (firmware) and the **Writer** again (build guide); the **Researcher** looks parts up. The **Inspector** (once called the Reviewer) checks every step before it starts, without the model: a brief that asks for something no part does (an RFID player with no reader), a supply too small, a box too small, an earlier step not passed. It stops the step with the reason and fixes, before minutes are spent on it. **Work log**, beside Run, shows who did what.

**Build** is the traveller: the eight steps as stations on a route card,
each stamped Passed, Failed or Unchecked. Unchecked means the step ran but
some of its checks could not -- which is not the same as passing. Choose a
step to see its checks in plain words and everything they found. **Run this
step** runs just that one; **Run to the end** carries on until a check
fails. Steps that need the language model say so, and if none is loaded Nemo
offers to load one. Model steps take minutes on this laptop; **Stop** ends
one immediately.

When a step fails, **Suggested fixes** appears under its checks: a bigger
supply, a larger enclosure, a missing protection circuit, or an instruction
for the model such as the real pin names of a part. Each shows exactly what
it would change. **Apply and run again** makes the change and re-runs the
step; **Apply only** makes the change so you can look first. Nothing is
applied unless you choose it, every applied fix is recorded in the project's
history so it can be undone, and no fix ever loosens a safety rule -- where
a rule is the only thing in the way, the suggestion is advice about what to
change in the design. The same suggestions are available as `nemo power`
and `nemo fix`.

**Files** lists everything the project has produced. Double-click to open.

**Sign-off** is the record that a person checked before printing, ordering
and connecting a battery, plus any safety items the design raised. Nemo
cannot stop you doing any of those things; it records that someone looked.

The header shows which model is loaded -- change it there -- and how much
memory is free, which on 8 GB decides what you can run. **Check this
machine** runs the same checks as `nemo doctor`.

| Key | Does |
|---|---|
| Ctrl+N | New project |
| Ctrl+S | Save the brief |
| F5 | Run the selected step |
| Esc | Stop the running step |

The window uses about 23 MB and needs no browser and no graphics driver.
Everything it does is also available as `nemo` commands in a terminal.

## Run this

**Double-click `NemoDoc.cmd`.** That is the whole procedure, first time and
every time after.

NemoDoc surveys the machine, installs or repairs whatever is missing, and
launches Nemo if everything passes. It is safe to run repeatedly -- it skips
anything already done, so a second run takes seconds. If something is wrong
it stops, names it, and does not launch a half-built system.

It needs Administrator and will ask for it. The `.cmd` wrapper exists
because Windows refuses to run `.ps1` files by default, which is the most
common reason a PowerShell installer appears to do nothing at all.

```
NemoDoc.cmd                    check, fix, launch
NemoDoc.cmd -CheckOnly         diagnose, change nothing
NemoDoc.cmd -NoLaunch          fix everything, do not start
NemoDoc.cmd -Mode design       pick the mode instead of auto-selecting
NemoDoc.cmd -SkipModels        skip the ~6.5 GB of downloads this pass
```

Log at `C:\Nemo\nemodoc.log`.

## What it handles for you

**Installs the right llama.cpp, verified.** llama.cpp now publishes one
Windows CPU package, `llama-<build>-bin-win-cpu-x64.zip`, which carries a
backend for each CPU generation and picks the right one when it starts:
`ggml-cpu-sandybridge.dll` on a Sandy Bridge Core chip, `ggml-cpu-sse42.dll`
on a Celeron or Pentium. NemoDoc downloads a pinned, inspected build
(b11175), checks its SHA-256 before unpacking, and then runs it to prove it
starts on this CPU. It does not use the GitHub API, which rate-limits
unauthenticated requests to 60 an hour per IP.

**Finds KiCad wherever it is.** KiCad installs into a folder named for its
version -- currently `C:\Program Files\KiCad\10.0\bin` -- and never adds
itself to PATH. NemoDoc searches every version folder, per-user installs and
the registry, picks the newest, adds its `bin` folder to your PATH, and sets
`NEMO_KICAD_CLI` so Nemo always finds the exact one.

**Works without winget.** App Installer comes from the Microsoft Store, and
plenty of bypass Windows 11 installs have no working Store. When winget is
missing NemoDoc falls back to direct downloads.

**Refreshes PATH mid-run.** Installers change the machine PATH but the
running process keeps its own copy, so without this every tool installed
during a pass looks missing for the rest of it.

**Resumes big downloads.** Models go through BITS where available, which
resumes and survives a flaky link. That matters when the file is gigabytes
and the Wi-Fi is 2011 vintage.

**Chooses the mode by free memory** at launch, not by what is installed.

## Installing llama.cpp by hand

Only if NemoDoc cannot reach GitHub.

1. From the releases page, download `llama-b11175-bin-win-cpu-x64.zip`.
   **Not** "Source code (zip)" -- that is the one containing `llama.h`, and
   it has no `llama-server.exe` in it at all.
2. Unzip **everything** into `C:\Nemo\engine\`. `llama-server.exe` is now a
   small launcher; it needs `llama-server-impl.dll`, `llama.dll`,
   `ggml.dll`, `ggml-base.dll` and the `ggml-cpu-*.dll` files beside it.
   Copying the `.exe` alone gives a missing-DLL error.
3. Run NemoDoc. It will verify the install and leave it in place.

`llama.h` is never needed. It is a C header used only when compiling
llama.cpp from source, and Nemo talks to `llama-server` over HTTP.

## The one thing it cannot do for you

Mesa -- and you may not need it. If Windows is using Intel's own driver for
this GPU (the AH531 this was built for kept Intel's final 2016 driver),
KiCad and FreeCAD already have the OpenGL they need, and NemoDoc says so.
Only if Windows has fallen back to the Basic Display Adapter do they need a
software renderer. Mesa's Windows builds are not published through an API
that can be queried reliably, so NemoDoc detects the need and tells you,
but you fetch the file:

1. Get mesa-dist-win, MSVC x64, desktop OpenGL drivers
2. Pick an **llvmpipe** build that is **not** compiled for AVX2 -- same
   reason as llama.cpp
3. `.\setup-mesa.ps1 -MesaZip C:\path\to\mesa.7z`

Undo with `.\setup-mesa.ps1 -Revert`.

## Optional

`.\trim.ps1` recovers roughly 800 MB to 1 GB from Windows: Search indexing
off, Widgets removed, best-performance visual effects, Defender exclusions
for the build tree, fixed page file. It does not touch security updates or
real-time protection, and everything it does is reversible.

## Modes

One model resident at a time. `nemo mode` refuses to start one that will not
fit in the memory available right now, counting the CAD tools you are about
to open as well as the model.

| mode | model | ctx | alongside |
|---|---|---|---|
| `talk` | Qwen3-1.7B | 8k | anything |
| `design` | Qwen3-4B | 4k | KiCad, not FreeCAD |
| `build` | Qwen2.5-Coder-3B | 4k | PlatformIO |
| `tiny` | Gemma 3 1B | 2k | fallback |

Context is 4k rather than 16k on the CAD modes because KV cache is real
memory and Windows has already spent two gigabytes of it.

## Usage after launch

```
nemo new chest "RFID card player in a treasure chest, USB powered"
nemo run
nemo check
nemo mode off
```

API key for the tier 2 reviewer, user environment only:

```powershell
setx NEMO_OPENROUTER_KEY "..."
```

## Folders

```
NemoDoc.cmd       run this
NemoDoc.ps1       the work
setup-mesa.ps1    software OpenGL
trim.ps1          reclaim memory
manual/           the old step-by-step installer, if you prefer it
packaging/        Inno Setup script, for putting this on another machine
nemo/             the package, including the parts library in nemo/data/parts
tests/  docs/
```

## If you want more headroom

NemoIso is the same core on Debian 13 with XFCE: idles near 1.2 GB instead
of 3.2, and Mesa's Crocus driver gives this GPU real hardware OpenGL 3.3
rather than software rendering. For CAD that is the biggest single
difference between the two. Dual-boot rather than replace.
