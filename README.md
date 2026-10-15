# UniFi Door

See who is at the door from the Omarchy bar. A door icon opens the picture of
the UniFi Protect camera watching your door (a G6 Pro Entry, a doorbell, an
intercom…), refreshed every few seconds while the panel is open.

Opening the door through UniFi Access is the next step and is not in this
version.

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

## Use

- **Click**: open the camera. **Middle click**: fetch a new picture now.
- In the panel: **r** refreshes, **s** runs setup, **Esc** closes.
- Settings: `camera` picks a camera by name or id (empty means the first door
  camera: Entry, Doorbell or Intercom models), and `refreshIntervalSec` sets
  how often the picture changes while the panel is open.

Pictures are fetched only while the panel is open, one at a time, and kept in
`$XDG_RUNTIME_DIR/omarchy-unifi-door/` (memory, private to you). Through the
cloud a picture takes about two seconds.

## Development

`lib/unifi` is a copy of the UniFi plugin's library, so both read the same
config and keyring. The only change is `Transport.get_bytes`, for JPEGs.

```bash
./test
```

## License

MIT
