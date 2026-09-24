# Getting started with PULSEFRAME

PULSEFRAME turns a song into a directed music video. You bring the song (and, if you have them, lyrics, a script and character art). PULSEFRAME listens, plans every shot on the beat, renders the shots with the AI video models you choose, checks them, and exports the finished video with your song as the soundtrack.

You stay the director. Nothing is ever charged to your accounts without a confirmation that shows the price first.

---

## 1. Connect your accounts (once)

Open **Settings** (the gear icon, or **File → Settings…**, `Ctrl+,`) and paste the keys you have. Keys are stored by Windows' secure credential store, never inside your projects.

| Key | What it's for | Needed? |
|---|---|---|
| **OpenAI** | The Director Engine (creative directions, treatment, shot direction) and visual Review | Recommended |
| **fal.ai** | Video and image models (Seedance, Kling, Veo, Wan, Hailuo, Happy Horse, Sora, Nano Banana, Seedream, lip-sync…) | At least one renderer |
| **Kie.ai** | The same families of models, billed in Kie credits | Optional |
| **Google Gemini** | Veo 3.1 video and Nano Banana images directly from Google | Optional |

You can start without any keys: song analysis and planning from a script work offline.

---

## 2. Start a music video

1. On the Home screen, **drop a song** onto the window or click **Choose Music** (MP3, WAV or M4A).
2. Give it a title.
3. **Lyrics** (optional, but worth it): paste them with section tags like `[Verse 1]`, `[Chorus]`, `[Bridge]`. PULSEFRAME uses them to find the song's real structure and to time every line.
4. **Script** (optional): if you've written scenes and shots (PDF or text), add it. PULSEFRAME will follow it exactly.
5. **Look** (optional): pick an art or animation style, e.g. *Feature animation 3D*, *Anime-inspired*, *Claymation*, *Cinematic live action*. Leave it on **Auto** to match your character art.
6. Click **Listen to the song**.

PULSEFRAME analyses tempo, beats, bars, energy, sections, the vocal and lyric timing. When it says **"I understand the song."**, click **Enter the Studio**.

---

## 3. Decide what the video is

**If you added a script**, your scenes and shots are already on the timeline, placed on the song.

**If you didn't**, the Studio asks *"How should this song look?"*:

1. Optionally type a note (e.g. *"set in Lagos, no dancing, hopeful ending"*).
2. Click **Show me three directions**. You get three different concepts (performance-led, performance + story, story-led) with premise, mood, performance, camera, world, movement, palette and a suggested look.
3. Pick one and click **Direct "…"**. PULSEFRAME writes the treatment and plans every shot on the beat.

Then press **Direct My Video** (top right). The Director Engine gives every shot full direction: purpose, emotion and intensity, acting, expression, blocking, lens and camera move, lighting, wardrobe and continuity, while keeping your story beats.

---

## 4. The Studio at a glance

- **Viewer** (centre): the current shot at your project's frame, with the lyric as a subtitle. Rendered takes play in sync with the song.
- **Timeline** (bottom): song sections in gold, waveform, lyrics and shot cards. Click a shot to select it; click anywhere to jump there. `Space` plays and pauses.
- **Inspector** (right): what you selected. Nothing selected shows the project: tempo, sections, story, cast, **Frame & quality** and **Look**.
- **Simple / Director Mode** (top): Simple shows only what you need. Director Mode reveals every control.

### Frame & quality (project-wide)

- **Aspect**: 2.39:1, 21:9, 16:9, 4:3, 1:1, 4:5 or 9:16. Each model uses its closest supported shape.
- **Quality**: Draft (fastest, cheapest), Standard (720p), High (1080p) or Max (the best the model offers).
- **Lip-sync**: on Auto, shots where a character sings are rendered with the matching slice of your song so the mouth follows the vocal.

---

## 5. Render

The recommended loop for each shot:

1. **Keyframe first.** Select a shot, then in the inspector click **Make a keyframe**. You get a still of the shot in a few seconds for a few cents. Make another if it's not right. When it is, click **Use for this shot**.
2. **Render the video.** Click **Render this shot**. The confirmation shows the estimated price. The video starts from your approved keyframe, so characters and composition stay consistent.
3. **Lip-sync (for singing close-ups).** On a finished take, click **Lip-sync this take…** to re-sync the mouth to the isolated vocal.

To render many shots at once, use **Render N shots** in the top bar (price shown before anything is sent).

Renders keep going if you close the app. When you reopen the project, PULSEFRAME reconnects to them. A shot is never sent twice by accident: if the app closed while a shot was being sent, it's marked **Check needed** and you decide.

---

## 6. Director Mode: full control

Switch to **Director Mode** and select a shot. The **Render** panel lets you:

- Choose the provider (fal.ai, Kie.ai, Google) and **any model** from their catalogues: Seedance, Kling, Veo, Wan, Hailuo, Happy Horse, Sora, Pixverse and more for video; Nano Banana, Seedream, Flux, GPT-image and more for keyframes.
- See **every input the model accepts**, grouped as Prompt, References, Format & quality, Motion & camera and everything else. Each shows whether PULSEFRAME filled it (**Auto**), you set it (**Pinned**) or the model's default applies.
- **Upload references**: images, videos and audio files from your computer (no links needed). They're copied into the project and sent to the model when you render. Models that use tags (e.g. `@Image1`, `@Video1`, `@Audio1`) show them next to each file.
- Change duration, aspect ratio, resolution, seed, camera controls: anything the model offers.
- **Show exact request** to see precisely what will be sent.

Pinned values win over PULSEFRAME's choices for that shot. **Reset** returns a field to Auto.

The **Look** picker in Director Mode also lets you edit the exact style wording and "avoid" list used for every shot.

---

## 7. Review

Every finished take is checked automatically:

- **Always** (free): long enough for its shot, no black or frozen frames, file readable.
- **With an OpenAI key**: frames are compared with your character sheet, the shot and your look for wrong faces, wardrobe changes, style drift, malformed hands, stray text or the wrong action.

Click **Review** on the left rail to see *"N shots may need attention"*. For each: **Fix** (re-render with the reviewer's corrections added) or **Keep this take**. **Fix all** handles every flag at once, after showing the price.

---

## 8. Export

Click **Export** on the left rail (`Ctrl+E`). Choose **YouTube 16:9**, **TikTok / Reels 9:16**, **Square 1:1** or **Cinema 2.39:1**. Each take is trimmed to its shot and placed on its exact frame; your song is the soundtrack. Shots not rendered yet appear as storyboard cards, so you can export a draft any time (the file name says *(draft)*). **Show in folder** opens the result.

---

## 9. Files and saving

- PULSEFRAME **saves as you work**. **File → Save** (`Ctrl+S`) confirms it.
- Each project is a folder in *Documents\PULSEFRAME* with a **.pulseframe** file inside. Double-click that file to open the project.
- **File → Save As…** makes a full copy (with media and takes) anywhere you choose.
- **File → Open Project…** (`Ctrl+O`) opens any `.pulseframe` file. Recent projects appear on the Home screen.

---

## 10. Costs and tips

- Every paid action shows its estimated price first. fal prices are live; Kie shows credits; Google bills your Google account.
- Try one shot on a couple of models before rendering everything; models differ a lot in price and style.
- Keyframes are the cheapest way to get the look right before paying for video.
- Tighter shots (under ~2 seconds) and shots with several story beats are the hardest for models; the Director Engine and Review flag them.
- Model lip-sync is good, not perfect; for hero close-ups, use **Lip-sync this take…**.

## Keyboard shortcuts

| Action | Shortcut |
|---|---|
| New music video | `Ctrl+N` |
| Open project | `Ctrl+O` |
| Save / Save As | `Ctrl+S` / `Ctrl+Shift+S` |
| Export | `Ctrl+E` |
| Simple / Director Mode | `Ctrl+1` / `Ctrl+2` |
| Toggle inspector | `Ctrl+I` |
| Play / pause | `Space` |
| Back / forward 5 seconds | `←` / `→` |
