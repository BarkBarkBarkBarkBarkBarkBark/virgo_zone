# Build: FairyLAN — Local-Only Jetson Social Site

Build a lightweight, polished local web application designed to run entirely on an NVIDIA Jetson connected to a normal Wi-Fi router.

People connected to the same LAN should be able to open the site from phones/laptops without installing anything.

Target access:

http://fairy.local:8080

The application MUST NOT require internet access and should remain useful when the WAN is completely disconnected.

## Product concept

Think:

* tiny private LAN social network
* party/camp/community bulletin board
* shared live photo wall
* group chat
* schedule
* mildly deranged local AI fairy commenting on things

The overall vibe should be:

**black terminal / cyberdeck × pastel rainbow fairy magic**

Not corporate.
Not Bootstrap.
Not generic AI dashboard.

It should feel strangely beautiful while using very little compute.

---

# Technical constraints

Optimize aggressively for simplicity and Jetson resource usage.

Use:

* Python 3
* FastAPI
* Uvicorn
* SQLite
* SQLite WAL mode
* native WebSockets
* server-rendered/static HTML
* vanilla JavaScript
* vanilla CSS
* Pillow for image thumbnails
* ffmpeg only where useful for video thumbnails/metadata
* Ollama HTTP API on localhost

Avoid unless absolutely necessary:

* React
* Next.js
* Node server
* Redis
* Postgres
* Docker
* Kubernetes
* large UI frameworks
* polling loops

This should ideally be one Python web service plus the existing Ollama service.

Run a SINGLE Uvicorn worker because the WebSocket connection manager can remain in-process.

Persist everything important to disk.

Suggested structure:

app/
main.py
db.py
models.py
websocket.py
ollama_client.py
media.py
settings.py
routes/
chat.py
media.py
schedule.py
ollama.py
static/
app.js
websocket.js
effects.js
styles.css
templates/
index.html
data/
app.db
uploads/
thumbnails/

Keep the architecture boring and understandable.

---

# Main UI

Prefer ONE responsive application rather than separate heavyweight pages.

Desktop:

LEFT:
schedule / upcoming events

CENTER:
live media feed/gallery

RIGHT:
chat

Mobile:

bottom navigation:

✨ Feed
💬 Chat
📅 Schedule

There should be a persistent small fairy/Ollama button somewhere in the interface.

---

# 1. Live media gallery

Users can upload:

* JPEG
* PNG
* WebP
* GIF if practical
* MP4
* MOV if browser-compatible

Each post has:

* UUID
* timestamp
* optional display name
* optional caption
* media filename
* media type
* thumbnail
* comments

Store ORIGINAL media files on disk.

Do NOT store blobs in SQLite.

SQLite only stores metadata.

Generate smaller image thumbnails for the feed so opening the site doesn't require loading every 5 MB photograph.

Use lazy-loading for gallery images.

Clicking/tapping an image opens a clean lightbox showing the full image and comments.

For video:

* create a poster thumbnail if ffmpeg is available
* don't autoplay every video
* only load/play when requested

When somebody uploads something:

1. validate file
2. assign UUID filename
3. save original
4. make thumbnail
5. insert metadata in SQLite
6. broadcast a WebSocket event
7. every connected browser immediately inserts the new post

NO PAGE REFRESH.

It should feel instantaneous.

On reconnect, clients fetch the authoritative current gallery state before consuming new WebSocket events, so missed events do not matter.

---

# 2. Photo comments

Every media item should have a comment thread.

Comment:

* id
* media_id
* author
* text
* created_at
* is_ai boolean

Adding a comment broadcasts:

media_comment_created

All clients viewing the image should see it immediately.

Allow emoji.

No rich HTML from users.

Render comments safely as text.

---

# 3. Chat

Create one general room initially.

Messages contain:

* id
* author
* text
* timestamp
* is_ai
* optional reply_to

The WebSocket system should deliver new messages immediately.

Keep approximately the latest 100 messages in the initial client load and allow older history to be loaded if requested.

Chat should work on phones particularly well.

Input remains pinned to the bottom.

Enter sends on desktop.

Provide a send button on mobile.

---

# 4. Ollama fairy

Ollama is already running locally on the Jetson.

DO NOT expose Ollama directly to clients.

Browser:

client → FastAPI → Ollama localhost:11434

Use Ollama's `/api/chat`.

Create an OLLAMA_MODEL environment setting rather than permanently hardcoding a model.

Also attempt to discover installed Ollama models and provide useful logging if the configured model isn't installed.

The AI character is called something like:

FAIRY

or

LAN FAIRY

Personality:

"You're the tiny weird fairy living inside this local network. Make very short, playful observations. Slightly absurd internet humor is encouraged. Don't explain yourself. Avoid cruelty or sensitive personal assumptions. Usually respond in one sentence."

Examples of desired energy:

"bro arrived geometrically 😭✨"

"the council has reviewed this image and unfortunately it goes hard"

"absolutely wizard behavior"

"extremely enchanted parking lot"

Do NOT make every response 2010s quirky Tumblr dialogue.

Keep it short.

The fairy should be able to participate in three ways.

### @fairy

If someone posts:

@fairy why is Marco standing like that

send the recent conversation context to Ollama and post its response as an AI chat message.

### Ask Fairy button

Every photo gets a tiny:

✨ fairy comment

button.

Clicking it invokes Ollama and inserts the answer directly into that photo's comments.

### Optional auto-comment mode

Create configuration:

FAIRY_AUTO_COMMENT=false

If enabled, uploaded photographs can automatically receive a fairy comment.

RATE LIMIT THIS.

Only allow one Ollama generation at a time.

Do not let 15 simultaneous uploads generate 15 simultaneous inference workloads.

Use an asyncio semaphore or lightweight inference queue.

---

# Vision

If the selected Ollama model supports vision, allow it to actually inspect uploaded images.

Send a resized derivative — NOT necessarily the giant original — to Ollama.

Make a roughly 1024px image derivative suitable for vision inference.

Do not repeatedly decode the original image.

If the configured model doesn't support vision, degrade gracefully.

It can comment based on:

* user's caption
* filename/media information
* conversation context

and the UI should not break.

Never require Ollama to render the gallery.

The whole website must continue working if Ollama is stopped.

AI is an enhancement, not a dependency.

---

# 5. Schedule

Simple shared schedule.

Event fields:

* id
* title
* description
* start datetime
* optional end datetime
* optional location
* created_at

Display:

TODAY
TOMORROW
UPCOMING

Make it visually nice rather than building a giant calendar application.

Example:

8:00 AM
Breakfast
Main Camp

11:00 AM
River

6:30 PM
Dinner

Schedule updates should also propagate using WebSockets.

Start with simple create/edit/delete controls behind admin mode.

Everybody else gets read-only schedule access.

---

# 6. Identity

Do NOT build full user accounts in v1.

When somebody first opens the site:

"what shall the network call you?"

They enter a display name.

Save:

display_name
random browser ID

to localStorage.

Send these with posts/messages.

Allow display name changes.

This isn't a security identity system.

It is just attribution for a trusted LAN.

Create a simple ADMIN_PASSWORD environment variable for modifying the schedule, deleting inappropriate media, etc.

---

# 7. Visual direction

This part matters.

Background:

#050505 / near-black

Surfaces:

transparent blacks
charcoal
subtle grey borders

Most borders approximately:

rgba(255,255,255,0.10)

Typography:

clean sans-serif

Can use system fonts initially.

Accent aesthetic:

PASTEL RAINBOW.

Think:

pink
lilac
baby blue
mint
soft yellow

but normally appearing as tiny accents rather than giant saturated blocks.

Cards should mostly remain black.

Use rainbow effects in:

* border glints
* focus states
* usernames
* tiny dividers
* loading states
* sparkles
* active navigation
* hover states

---

# Fairy effects

I want motion but I specifically DON'T want the effects chewing GPU constantly.

Use CSS transforms/opacity wherever possible.

No permanent full-screen canvas animation.

Effects:

### Click/tap sparkle

When clicking somewhere interesting, emit approximately 4–8 tiny stars/dots around the interaction point.

Pastel random colors.

Particles:

* scale outward
* rotate
* fade
* remove DOM nodes after animation

Cap total active particles.

### Scroll glints

As cards enter the viewport:

* tiny border sheen
* 1–2 second subtle rainbow shimmer
* then become static

Use IntersectionObserver.

DO NOT continuously animate every card.

### Hover

On desktop:

subtle pastel border light follows or activates around gallery cards.

Don't implement expensive mouse tracking across hundreds of elements.

### New post

When a WebSocket gallery item arrives:

slight scale-in
small sparkle near top corner
rainbow border flash
then completely settles

### Fairy messages

AI messages get:

✨ small star
subtle rainbow-left border
slightly strange visual treatment

but remain readable.

Support:

prefers-reduced-motion

and disable decorative animations accordingly.

---

# Performance philosophy

Pretty while idle should essentially cost nothing.

Animations should happen because something happened:

* click
* upload
* new message
* card entering viewport
* hover

Not because a background animation is running forever.

Use:

requestAnimationFrame
CSS opacity
CSS transform
IntersectionObserver

Avoid expensive blur everywhere.

A little backdrop-filter is acceptable on major navigation surfaces, but don't blur every gallery card.

---

# Database

SQLite is appropriate.

Enable:

PRAGMA journal_mode=WAL;

Create tables approximately:

users
chat_messages
media
media_comments
schedule_events

Possibly app_settings if needed.

Use migrations or at minimum a clean database initialization layer.

Do not scatter CREATE TABLE statements throughout route handlers.

---

# WebSocket protocol

Use one endpoint:

/ws

Messages should be small JSON envelopes like:

type
payload

Potential event types:

chat_created
media_created
media_deleted
media_comment_created
schedule_created
schedule_updated
schedule_deleted
fairy_typing
fairy_finished

Clients must reconnect automatically with exponential backoff.

After reconnect:

refresh current application state.

Do not attempt some giant complex distributed event architecture.

---

# Upload safety

Even though this is LAN-only, treat uploads carefully.

Implement:

* maximum upload size
* allowed MIME types
* actual MIME inspection where practical
* UUID filenames
* strip original paths
* never execute uploaded files
* don't render arbitrary HTML
* don't accept SVG initially
* reject executables
* sanitize captions/comments
* protect deletion/admin endpoints
* basic rate limiting

Suggested configurable limits:

IMAGE_MAX_MB=20
VIDEO_MAX_MB=250

Make them environment settings.

---

# Storage

Create:

data/uploads/YYYY/MM/

and:

data/thumbnails/YYYY/MM/

Do not use one giant directory forever.

Provide an admin storage display:

23.4 GB free
3.2 GB media

If disk space becomes dangerously low, reject new uploads with a clear message rather than crashing the Jetson.

---

# Network deployment

FastAPI/Uvicorn should listen on:

0.0.0.0:8080

but Ollama should remain reachable only through localhost whenever possible.

Set hostname:

fairy

Use Avahi/mDNS so clients can access:

http://fairy.local:8080

Also show the raw LAN IP during startup in case mDNS doesn't work.

Build a systemd service so the application:

* launches at boot
* restarts after crashes
* logs to journalctl

Do NOT require somebody to SSH in and manually start it.

---

# Failure behavior

This matters.

If Ollama goes down:

gallery works
chat works
schedule works

and the fairy shows:

"fairy is sleeping"

If thumbnail generation fails:

keep original upload and show fallback UI.

If WebSocket disconnects:

show tiny offline indicator
automatically reconnect.

If database fails:

log a useful error rather than silently swallowing it.

If storage is nearly full:

disable uploads gracefully.

---

# API

Keep the REST API small.

Something roughly equivalent to:

GET /api/bootstrap
GET /api/media
POST /api/media
DELETE /api/media/{id}

POST /api/media/{id}/comments
POST /api/media/{id}/fairy

GET /api/chat
POST /api/chat

GET /api/schedule
POST /api/schedule
PATCH /api/schedule/{id}
DELETE /api/schedule/{id}

POST /api/fairy/chat

GET /api/status

GET /api/status should show:

server OK
database OK
Ollama reachable/unreachable
configured Ollama model
disk free
WebSocket client count

Do not expose sensitive machine information unnecessarily.

---

# Bootstrap endpoint

I would particularly like:

GET /api/bootstrap

to return everything required to initially render:

* schedule
* latest gallery posts
* latest chat messages
* application name
* feature flags
* Ollama online state

This minimizes initial HTTP request spam.

---

# Testing

Write actual tests rather than telling me it probably works.

At minimum test:

* database initialization
* chat message creation
* media metadata creation
* comment creation
* schedule CRUD
* upload type validation
* upload size validation
* admin authorization
* Ollama unavailable behavior
* WebSocket broadcast serialization

Also create a lightweight manual LAN test checklist.

Test with simulated multiple connected WebSocket clients if possible.

---

# Performance targets

The web application itself, NOT including Ollama, should be extremely lightweight.

Aim for:

* fast initial page load
* minimal idle CPU
* no constant GPU animation
* responsive with at least 10–20 LAN clients
* hundreds/thousands of gallery records without loading everything simultaneously

Paginate older gallery content.

Use thumbnail derivatives.

Do not preload videos.

Do not poll the server every second.

---

# Build sequence

Do this incrementally and KEEP THE APP RUNNABLE after each major step.

### Phase 1

Scaffold FastAPI project.

Implement:

SQLite
static frontend
/api/status
/api/bootstrap
system settings

### Phase 2

Chat + WebSockets.

Open two browser windows and prove messages appear in both instantly.

### Phase 3

Photo uploads + gallery.

Open two browsers.

Upload from one.

Prove image appears in the other without refresh.

### Phase 4

Media comments.

Prove comment appears on both clients instantly.

### Phase 5

Schedule CRUD + admin authentication.

### Phase 6

Ollama integration.

First prove ordinary text chat works.

Then detect/configure vision capability.

Then implement image comments.

### Phase 7

Add fairy visual system.

Only AFTER functionality works.

### Phase 8

Jetson deployment:

systemd
mDNS
startup
network accessibility
storage checks

### Phase 9

Stress/manual testing from multiple devices.

---

# Important engineering rule

Do not disappear into architecture astronautics.

This application is running on one Jetson for people sitting on one LAN.

Choose the smallest reliable solution.

I want code that I can understand, repair and vibe-code on later.

Prefer:

50 lines I understand

over:

a framework that solves a theoretical scaling problem I do not have.

---

# First task

Before changing anything:

1. inspect the Jetson/project environment
2. confirm Python version
3. confirm ffmpeg availability
4. check that Ollama responds on localhost
5. list the installed Ollama models
6. identify the Jetson's LAN interface/IP
7. show me the proposed directory structure
8. then scaffold Phase 1

After each phase:

RUN THE APPLICATION.

Test the feature rather than merely generating code.

Do not declare a phase complete because files exist.

Prove behavior.

The most important end-to-end test is:

PHONE A uploads a picture → PHONE B sees it immediately → PHONE B comments → PHONE A sees the comment immediately → somebody presses ✨ fairy comment → Ollama looks at the picture and says something stupid.
