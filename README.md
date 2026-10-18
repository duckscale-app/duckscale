<p align="center">
  <img src="assets/logo.png" alt="Duckscale logo" width="160">
</p>

# Duckscale

A small Linux desktop app for two everyday Tailscale tasks: switching your
connection on or off, and moving between accounts.

Built for Linux Mint Cinnamon with Python 3, GTK 3, and an optional system tray.
The official `tailscaled` service handles networking and credentials.

## Features

- Enable or disable Tailscale with daemon-confirmed status.
- Switch between saved accounts from the window or tray.
- Add an account through Tailscale's browser sign-in flow.
- Cancel sign-in and return to the previous saved account.
- Automatic refresh and recovery after daemon interruptions.
- Per-account DNS, subnet routes, incoming connections, and exit-node LAN settings.
- Application-menu launcher and optional start-at-login installation.

## Quick start

Install the official Tailscale Linux package and ensure `tailscaled` is running.
On Linux Mint / Ubuntu, install the desktop dependencies:

```sh
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
```

From the checkout:

```sh
python3 -m duckscale
```

If Duckscale reports permission denied, explicitly authorize your regular user
as a Tailscale operator:

```sh
sudo tailscale set --operator="$USER"
```

This grants your user Tailscale administration access. Duckscale runs without
root and never changes socket permissions or invokes sudo.

## Install for your user

```sh
make install
```

Open **Duckscale** from the application menu. To also start it in the tray when
you log in, use this instead:

```sh
python3 scripts/install.py --autostart
```

Installation copies the app into `$XDG_DATA_HOME/duckscale` (normally
`~/.local/share/duckscale`) and creates `~/.local/bin/duckscale` and a desktop
launcher. Re-run installation after updating the checkout. To disable autostart,
remove `duckscale.desktop` from `$XDG_CONFIG_HOME/autostart` (normally
`~/.config/autostart`), or use your desktop's Startup Applications settings.

## Accounts and connection behavior

**Add account** pauses your current connection and opens Tailscale's sign-in page
in your default browser. Existing saved accounts are retained. Finish signing
in to activate the account, or choose **Cancel sign-in** to return to the previous
profile. If there was no previous profile, cancellation returns to an unsigned-in
profile. Closing Duckscale does not cancel browser authentication; saved accounts
remain available when you reopen it.

Switching accounts uses the target profile's saved connection preferences. It
may connect immediately if that account was enabled. Enabling or disabling patches
only the run preference; DNS, routes, and exit-node settings remain intact.

If account-management access is denied, readable connection status remains visible
and Duckscale shows the exact operator setup command. Failed actions retain the
last known status. Background refresh does not disable controls.

Controls are serialized and do not claim success until the daemon confirms the
requested state. Refresh runs every three seconds. Closing the window leaves the
tray running; **Quit Duckscale** exits the UI without disconnecting Tailscale.
Without AppIndicator, the window remains usable. GNOME may need an AppIndicator
extension to display the tray.

## Connection settings

Open the gear button in the window, or **Settings…** in the tray. You can change:

- **Use Tailscale DNS:** accept this tailnet’s DNS configuration.
- **Accept subnet routes:** use networks advertised by subnet routers.
- **Allow incoming connections:** permit connections subject to tailnet access
  policy and your local firewall; disabling this enables Tailscale shields-up.
- **Allow local network with an exit node:** retain direct LAN access when an
  exit node is in use. This does not select or enable an exit node.

Only changed settings are saved, and the daemon’s stored values are checked
before reporting success. Settings belong to the active account. If the account
changes before saving, Duckscale rejects the save and asks you to reopen settings.

## Development

No pip packages or web runtime are required. Use the distribution Python with
PyGObject installed (`/usr/bin/python3` on Mint).

```sh
make test
# GTK flow test using fake accounts; requires xvfb:
PYTHONPATH=.:tests xvfb-run -a /usr/bin/python3 tests/smoke_ui.py
```

Tests cover masked connection changes, account confirmation, timeouts, permissions,
authentication URL validation, login cancellation/restoration, installation, and
GTK login completion. They do not change your live Tailscale connection.

```sh
python3 -m duckscale --help
python3 -m duckscale --background
python3 -m duckscale --socket /path/to/tailscaled.sock
```

## Compatibility and release status

Version 0.1.1 is an initial release. Linux Mint/Cinnamon is the primary target;
other GTK desktops have not been comprehensively tested. Read-only integration
was checked with Tailscale 1.104.1. Login and connection mutations were verified
against test doubles, not a real authentication provider. The LocalAPI can evolve,
so compatibility testing remains necessary as Tailscale changes.

Duckscale is an independent project, not affiliated with or endorsed by Tailscale.
