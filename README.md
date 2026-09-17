# Spotipip

Spotipip is a small Linux application written in Python/PyQt6 that displays the synchronized lyrics of the currently playing Spotify track in a **Picture-in-Picture** window.

The window can remain **always on top** and, by pressing the `📌` button, can become **click-through**: the lyrics remain visible while mouse clicks are passed to the window underneath. A small separate `🔓` button allows you to unlock the overlay again.

The project is designed for **NixOS**, with particular attention to **GNOME + Mutter + XWayland**.

## Main Features

- Synchronized lyrics updated according to the current track position.
- Lyrics lookup through **LRCLIB**, with **NetEase** as a fallback.
- Local lyrics cache in `~/.cache/spotify-pip`.
- Spotify controls for previous track, play/pause, and next track.
- Frameless and translucent window.
- `📌` click-through mode: the window remains visible but does not intercept mouse clicks.
- Floating `🔓` button for leaving locked mode.
- Always-on-top through EWMH `_NET_WM_STATE_ABOVE`.
- In lock mode the Qt window is not recreated: click-through uses the **X11/XWayland Input Shape**, avoiding loss of the lyrics rendering.
- Complete Nix package with `.desktop` launcher and application icons.

## Requirements

The intended environment is:

- Nix/NixOS with **flakes** and **nix-command** enabled.
- A Linux graphical session with **XWayland** available.
- Spotify running.
- Spotify must expose its player through **MPRIS**, because the application uses `playerctl` to read the title, artist, position, and playback state and to send media commands.
- GNOME/Mutter is the primary environment for which the Always-On-Top behavior was designed.

The `flake.nix` forces `QT_QPA_PLATFORM=xcb` and includes `libX11` and `libXfixes`, which are required for native window handling under XWayland.

## Installing on NixOS

### 1. Clone the project

```bash
git clone https://github.com/genna2222/spotipip.git
cd spotipip
```

Or simply enter the project directory if you already have a local checkout.

### 2. Make sure flakes and nix-command are enabled

Check your Nix version with:

```bash
nix --version
```

If flakes and `nix-command` are not already enabled on your NixOS system, add the following to your NixOS configuration:

```nix
{
  nix.settings.experimental-features = [ "nix-command" "flakes" ];
}
```

Then rebuild the system:

```bash
sudo nixos-rebuild switch
```

### 3. Run without installing

To try the application directly from the project directory:

```bash
nix run .
```

This builds the package defined by the flake and launches `spotipip`.

### 4. Install into your user profile

To install it into your Nix user profile:

```bash
nix profile install .
```

After installation, start it with:

```bash
spotipip
```

The package also installs the desktop entry and application icons, so GNOME can show Spotipip in the application menu.

### 5. Install through a NixOS flake configuration

If you prefer to manage Spotipip directly from your system configuration, add the repository as an input to your NixOS flake.

Example:

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    spotipip.url = "github:genna2222/spotipip";
  };

  outputs = { self, nixpkgs, spotipip, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
    in {
      nixosConfigurations.my-pc = nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs; };
        modules = [
          ./configuration.nix
        ];
      };
    };
}
```

Then, inside `configuration.nix` or a module imported by it:

```nix
{ pkgs, inputs, ... }:

{
  environment.systemPackages = [
    inputs.spotipip.packages.${pkgs.system}.default
  ];
}
```

Finally:

```bash
sudo nixos-rebuild switch --flake .#my-pc
```

> Note: `my-pc` is only an example and must match the name used in your `nixosConfigurations`.

## Local Development

To enter the development environment provided by the flake:

```bash
nix develop
```

The development shell provides:

- Python with PyQt6 and Requests.
- `playerctl`.
- `xdg-utils`.
- `libX11`.
- `libXfixes`.
- `QT_QPA_PLATFORM=xcb`.
- `LD_LIBRARY_PATH` containing the required X11 libraries.

From the development shell, you can run the application directly:

```bash
python spotify_pip.py
```

## Usage

### Normal Launch

Start Spotipip while Spotify is running:

```bash
spotipip
```

The window displays the current track and automatically updates the synchronized lyrics.

### `▶ / ⏸` Button

The center button in the bottom bar controls Spotify playback through `playerctl`.

### `⏮` and `⏭` Buttons

Use these buttons to switch to the previous or next track.

### Moving the Window

When the window is unlocked, you can drag it with the mouse.

### Resizing the Window

When the window is unlocked, a resize handle is available in the lower-right corner.

### `📌` Button — Lock / Click-Through Mode

Pressing `📌`:

1. hides the controls that are not needed;
2. makes the overlay background transparent;
3. keeps the window above other applications;
4. clears its X11 input shape;
5. allows mouse clicks to pass through Spotipip to the application underneath;
6. keeps the lyrics visible and updated.

This mode is ideal for reading lyrics while using a browser, editor, or terminal underneath the overlay.

### `🔓` Button — Unlock

When Spotipip is locked, a small green `🔓` button appears as a separate floating window.

Clicking it:

- makes the overlay interactive again;
- restores the controls;
- allows you to move and resize the window again;
- disables click-through mode.

## Lyrics and Cache

The application looks for lyrics in this order:

1. local cache;
2. LRCLIB using an exact lookup;
3. LRCLIB using a general search;
4. NetEase as a fallback.

Cached files are stored in:

```text
~/.cache/spotify-pip/
```

The cache is used automatically to avoid repeated network requests.

### Reloading Lyrics

With the window unlocked, the context menu provides:

- `Reload (use cache)`
- `Reload and download again (ignore cache)`
- `Close`

Open the context menu by right-clicking the window.

## Starting Automatically with GNOME

The package installs:

```text
share/applications/spotipip.desktop
```

with:

```text
Exec=spotipip
```

This allows Spotipip to be launched from the GNOME application menu.

To start Spotipip automatically at login, you can use GNOME's startup applications settings or create a user `.desktop` file that runs the `spotipip` command.

## Troubleshooting

### Spotipip starts but cannot see Spotify

Make sure Spotify is running and that `playerctl` can access it:

```bash
playerctl -p spotify status
playerctl -p spotify metadata title
playerctl -p spotify metadata artist
playerctl -p spotify position
```

If these commands return no data, the issue is upstream of Spotipip: Spotify must be reachable through MPRIS/`playerctl`.

### Lyrics are not found

Not every track has synchronized lyrics available from the services queried by the application. You can force a fresh download from the context menu with:

```text
Reload and download again (ignore cache)
```

### `📌` Click-Through Mode Does Not Pass Clicks

Click-through depends on the **X11/XWayland** path used by this build. The flake sets:

```text
QT_QPA_PLATFORM=xcb
```

and includes the `libX11` and `libXfixes` libraries.

Make sure XWayland is available in your graphical session.

### The Window Does Not Stay on Top

The application asks Mutter to set the EWMH `_NET_WM_STATE_ABOVE` state and periodically reasserts it, including when the window loses focus. The intended environment is GNOME/Mutter with XWayland.

### Running from Source Without Nix

You can use the development environment directly:

```bash
nix develop
python spotify_pip.py
```

Using `nix run .` or `nix profile install .` is recommended because the flake also provides the native X11 libraries and the wrapper configured with `QT_QPA_PLATFORM=xcb`.

## Updating

If the project was installed with `nix profile install`, pull the latest changes and reinstall:

```bash
git pull
nix profile install . --refresh
```

If you run it directly with `nix run .`, update the repository and launch it again:

```bash
git pull
nix run .
```

## Uninstalling

To remove Spotipip from a Nix user profile:

```bash
nix profile list
```

Find the `spotipip` entry, then remove it with:

```bash
nix profile remove <INDEX>
```

If you added it to `environment.systemPackages` in your NixOS configuration, remove the corresponding entry from `configuration.nix` or the relevant module and rebuild:

```bash
sudo nixos-rebuild switch
```

## Project Structure

The main files are:

```text
.
├── flake.nix
├── spotify_pip.py
├── spotipip.desktop
├── spotipip.svg
└── spotipip.png
```

### `spotify_pip.py`

Implements the PyQt6 GUI, lyrics retrieval and parsing, Spotify control, and X11/XWayland handling for click-through and Always-On-Top.

### `flake.nix`

Defines the Nix package, development shell, Python dependencies, native X11 libraries, and the `spotipip` executable wrapper.

### `spotipip.desktop`

Defines integration with the Linux desktop application menu.

## License

The project flake declares the **MIT** license.
