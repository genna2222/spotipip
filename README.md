Ecco il file `README.md` aggiornato in lingua inglese, con la ridenominazione completa in **Lyripip**, il supporto dual-player per **Spotify** e **Feishin**, l'inclusione del pulsante preferiti e tutti i comandi/percorsi allineati:

```markdown
# Lyripip

Lyripip is a lightweight Linux application written in Python/PyQt6 that displays the synchronized lyrics of the currently playing track from **Spotify** or **Feishin** in a **Picture-in-Picture** window.

The window stays **always on top** and, by pressing the `📌` button, enters **click-through** mode: the lyrics remain visible while mouse clicks pass directly to the window underneath. A small separate `🔓` floating button lets you exit locked mode at any time.

The project is tailored for **NixOS**, with explicit support for **GNOME + Mutter + XWayland**.

## Main Features

- Synchronized lyrics updated in real time based on the active player's track position.
- **Multi-Player MPRIS support**: automatically detects playback from **Spotify** and **Feishin**.
- Lyrics lookup through **LRCLIB**, with **NetEase Music** as a fallback.
- Local lyrics caching in `~/.cache/lyripip`.
- Media playback controls: previous track, play/pause, and next track.
- **Local Favorites (`♡` / `♥`)**: toggle tracks into a local favorites list (`~/.cache/lyripip/favorites.txt`).
- Frameless and translucent overlay.
- `📌` click-through mode: hides controls and ignores mouse events while keeping lyrics visible.
- Floating `🔓` button to unlock the overlay.
- Always-on-top management via EWMH `_NET_WM_STATE_ABOVE` on XWayland.
- Packaged natively with Nix flakes, including `.desktop` integration and scalable application icons.

## Requirements

The intended environment is:

- Nix/NixOS with **flakes** and **nix-command** enabled.
- A Linux graphical session with **XWayland** available.
- Either **Spotify** or **Feishin** running.
- The media player must expose an **MPRIS** interface (managed via `playerctl` for metadata, position, and playback state).
- GNOME/Mutter is the primary environment targeted for the Always-On-Top and XWayland input-shape behavior.

The `flake.nix` sets `QT_QPA_PLATFORM=xcb` and includes `libX11` and `libXfixes` for native window handling under XWayland.

## Installing on NixOS

### 1. Clone the project

```bash
git clone [https://github.com/genna2222/spotipip.git](https://github.com/genna2222/spotipip.git) lyripip
cd lyripip

```

### 2. Ensure flakes and nix-command are enabled

Verify your Nix version:

```bash
nix --version

```

If flakes and `nix-command` are not enabled yet, add the following to your NixOS configuration:

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

This builds the package defined by the flake and executes `lyripip`.

### 4. Install into your user profile

To install Lyripip into your current Nix profile:

```bash
nix profile install .

```

After installation, launch it with:

```bash
lyripip

```

The package installs desktop entries and application icons, making Lyripip available in your desktop application launcher.

### 5. Install through a NixOS flake configuration

Add the repository input to your system `flake.nix`:

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    lyripip.url = "github:genna2222/spotipip"; # or github:genna2222/lyripip
  };

  outputs = { self, nixpkgs, lyripip, ... }:
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

Then, in `configuration.nix` or an imported module (e.g., `software.nix`):

```nix
{ pkgs, inputs, ... }:

{
  environment.systemPackages = [
    inputs.lyripip.packages.${pkgs.system}.default
  ];
}

```

Rebuild your system:

```bash
sudo nixos-rebuild switch --flake .#my-pc

```

## Local Development

To enter the flake-provided development shell:

```bash
nix develop

```

The development shell provides:

* Python with PyQt6 and Requests.
* `playerctl`.
* `xdg-utils`.
* `libX11`.
* `libXfixes`.
* `QT_QPA_PLATFORM=xcb`.
* `LD_LIBRARY_PATH` configured for X11 libraries.

From inside the development shell, run the script directly:

```bash
python spotify_pip.py

```

## Usage

### Launching

Start Lyripip while Spotify or Feishin is running:

```bash
lyripip

```

The overlay will automatically detect playback and fetch matching synchronized lyrics.

### `▶ / ⏸` Button

Controls playback (play/pause) on the active player via `playerctl`.

### `⏮` and `⏭` Buttons

Skips to the previous or next track.

### `♡ / ♥` Button — Local Favorites

Clicking the heart icon adds or removes the current track from your local favorites list stored in `~/.cache/lyripip/favorites.txt`.

### Moving the Window

When unlocked, drag anywhere on the window using the left mouse button.

### Resizing the Window

When unlocked, drag the resize grip located at the bottom-right corner.

### `📌` Button — Lock / Click-Through Mode

Pressing `📌`:

1. Hides window controls and secondary badges.
2. Sets a fully transparent container background.
3. Preserves Always-On-Top elevation.
4. Empties the X11 input shape mask.
5. Passes all clicks directly to windows underneath while keeping lyrics visible.

### `🔓` Button — Unlock

When locked, a floating green `🔓` button appears in place of the pin. Clicking it restores the full interactive window and media controls.

## Lyrics and Cache

Lyrics are retrieved using the following fallback sequence:

1. Local disk cache (`~/.cache/lyripip/`).
2. LRCLIB exact match.
3. LRCLIB fuzzy search query.
4. NetEase Music search API.

### Context Menu Actions

Right-click anywhere on the unlocked window to open the context menu:

* **Reload (use cache)**: Re-reads lyrics from the local cache.
* **Reload and download again (ignore cache)**: Deletes the cached file and performs a fresh query across providers.
* **Close**: Exits the application.

## Troubleshooting

### Lyripip starts but does not detect playback

Ensure Spotify or Feishin is running and exporting MPRIS properties:

```bash
playerctl -l
playerctl metadata title
playerctl metadata artist

```

If `playerctl -l` does not list `spotify` or `feishin`, check that the player has MPRIS integration enabled.

### Click-Through Mode does not pass clicks

Click-through relies on X11/XWayland input shapes. Verify that your desktop session supports XWayland and that the wrapper runs with:

```bash
echo $QT_QPA_PLATFORM # Should output: xcb

```

### The window does not stay on top

Lyripip applies the `_NET_WM_STATE_ABOVE` atom directly to the native X11 window and reasserts it periodically. Ensure GNOME Mutter has not disabled custom above-state hints for frameless windows.

## Project Structure

```text
.
├── flake.nix
├── spotify_pip.py
├── lyripip.desktop
├── lyripip.svg
└── lyripip.png

```

## License

Distributed under the [MIT](https://www.google.com/search?q=LICENSE&utm_source=gemini) license.

```

```