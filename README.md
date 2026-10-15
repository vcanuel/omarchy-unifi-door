# UniFi Door

See who is at the door from the Omarchy bar, and let them in. A door icon
opens the picture of the UniFi Protect camera watching your door (a G6 Pro
Entry, a doorbell, an intercom…), refreshed every few seconds while the panel
is open, with the UniFi Access door below it: locked or not, open or closed,
and an **Open** button.

## Install

```bash
omarchy plugin add https://github.com/vcanuel/omarchy-unifi-door.git --enable
```

## Setup

The plugin shares its console profiles and API keys with the
[UniFi plugin](https://github.com/vcanuel/omarchy-unifi): if that one is set
up, there is nothing to do. Otherwise click the icon and press **s**, or run:

```bash
~/.config/omarchy/plugins/vcanuel.unifi-door/bin/unifi-door setup
```

The key from UniFi Network (**Settings → Control Plane → Integrations**) also
reads Protect, on the LAN and through the UniFi cloud. A read-only key is
enough.

### Opening the door (UniFi Access)

Access is only reachable on the console itself (port 12445), so the door part
works on the console's network or over a VPN to it (WireGuard or Teleport on a
UniFi gateway). The UniFi cloud does not relay Access. The camera keeps
working either way.

1. In **UniFi Access → Settings → General → API Token**, create a token with
   only: **Locations: Edit** (this is what unlocks), **Device: View**,
   **System Log: View**. Leave everything else on **None**: the default
   grants edit rights on users, policies and credentials.
2. Press **a** in the panel, or run
   `~/.config/omarchy/plugins/vcanuel.unifi-door/bin/unifi-door access-setup`.
   It asks for the console address, shows Access's certificate to pin, and
   stores the token in your keyring.

## Use

- **Click**: open the camera. **Middle click**: fetch a new picture now.
- **Open** unlocks the door, in two steps: the first press arms the button for
  four seconds ("Click again"), the second one unlocks. The lock closes again
  by itself after the delay set in Access. Nothing else ever unlocks.
- In the panel: **r** refreshes, **u u** unlocks, **s** runs setup, **a** sets
  up Access, **Esc** closes.
- Settings: `camera` picks a camera by name or id (empty means the first door
  camera: Entry, Doorbell or Intercom models), `door` picks the Access door
  (empty means the first one wired to a hub), and `refreshIntervalSec` sets
  how often the picture and the door's state refresh while the panel is open.

Pictures are fetched only while the panel is open, one at a time, and kept in
`$XDG_RUNTIME_DIR/omarchy-unifi-door/` (memory, private to you). Through the
cloud a picture takes about two seconds.

## Development

`lib/unifi` is a copy of the UniFi plugin's library, so both read the same
config and keyring. The only changes are `Transport.get_bytes` (JPEGs) and
`Transport.request` (Access's bearer token and PUT). Access has its own
address and pinned certificate in `~/.config/omarchy-unifi-door/config.json`
and its token in the keyring (`service omarchy-unifi-door`).

```bash
./test
```

## License

MIT
