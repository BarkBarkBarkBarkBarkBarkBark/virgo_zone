# VirgoZone manual LAN acceptance

## Boot and discovery

- [ ] Reboot the Jetson without an SSH session.
- [ ] Confirm `systemctl is-active virgozone ollama avahi-daemon` reports active.
- [ ] Open `http://virgozone.local:8080` from a phone on the same Wi-Fi.
- [ ] Open the raw LAN IP if mDNS is unavailable.
- [ ] Confirm `/api/status` reports server and database OK.

## Two-device workflow

- [ ] Phone A chooses a display name and Phone B chooses a different name.
- [ ] Phone A sends chat; Phone B sees it without refresh.
- [ ] Phone A uploads a JPEG; Phone B sees the thumbnail without refresh.
- [ ] Phone B opens the photo and comments; Phone A sees it without refresh.
- [ ] Press fairy comment; both devices see either the AI comment or a clear
      `fairy is sleeping` state without breaking the thread.
- [ ] Restart VirgoZone and verify chat, media, and comments remain.

## Media and safety

- [ ] JPEG, PNG, WebP, and GIF images create small lazy feed thumbnails.
- [ ] MP4/MOV does not autoplay and does not load until opened.
- [ ] A renamed SVG or executable is rejected.
- [ ] An image over 20 MB and video over 250 MB are rejected.
- [ ] `/api/status` reports free disk and media storage.
- [ ] Lower `MIN_FREE_MB` test configuration proves low-storage rejection.

## Schedule and admin

- [ ] A non-admin cannot create, edit, delete, or remove media.
- [ ] The shared password unlocks create/edit/delete schedule controls.
- [ ] Schedule changes arrive immediately on the second device.
- [ ] Logout removes the mutation controls.

## Failure and offline behavior

- [ ] Disconnect WAN while leaving the LAN router active.
- [ ] Reload both devices; local CSS, JavaScript, chat, gallery, and schedule work.
- [ ] Stop Ollama; all non-fairy features continue and fairy reports sleeping.
- [ ] Restart Ollama; fairy calls recover without restarting VirgoZone.
- [ ] Interrupt a WebSocket connection; the indicator changes and the browser
      reconnects, reboots state, and does not duplicate messages.

## Load and idle behavior

- [ ] Connect 20 WebSocket clients and send one chat event to all.
- [ ] Scroll through enough posts to exercise cursor pagination.
- [ ] Verify browser network tools show no periodic polling while idle.
- [ ] Verify sparkles/glints settle and no decorative animation runs continuously.
- [ ] Enable reduced motion and verify decorative effects are disabled.
