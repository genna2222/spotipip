{
  description = "Spotify PiP Lyrics overlay per NixOS (GNOME Always-On-Top fix)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };

        pythonEnv = pkgs.python3.withPackages (
          ps: with ps; [
            pyqt6
            requests
          ]
        );

        spotifyPipPkg = pkgs.stdenv.mkDerivation {
          pname = "spotipip";
          version = "1.0.4";

          src = ./.;

          nativeBuildInputs = [ pkgs.makeWrapper ];

          installPhase = ''
            runHook preInstall
            mkdir -p $out/lib/spotipip
            cp spotify_pip.py $out/lib/spotipip/
            cp spotipip.png $out/lib/spotipip/
            cp spotipip.svg $out/lib/spotipip/

            mkdir -p $out/bin
            makeWrapper ${pythonEnv}/bin/python $out/bin/spotipip \
              --add-flags "$out/lib/spotipip/spotify_pip.py" \
              --set QT_QPA_PLATFORM xcb \
              --prefix LD_LIBRARY_PATH : "${pkgs.lib.makeLibraryPath [ pkgs.xorg.libX11 pkgs.xorg.libXfixes ]}" \
              --prefix XDG_DATA_DIRS : "$out/share" \
              --prefix PATH : ${
                pkgs.lib.makeBinPath [
                  pkgs.playerctl
                  pkgs.xdg-utils
                ]
              }

            mkdir -p $out/share/applications
            cp spotipip.desktop $out/share/applications/

            mkdir -p $out/share/icons/hicolor/scalable/apps
            cp spotipip.svg $out/share/icons/hicolor/scalable/apps/spotipip.svg

            mkdir -p $out/share/icons/hicolor/256x256/apps
            cp spotipip.png $out/share/icons/hicolor/256x256/apps/spotipip.png
            runHook postInstall
          '';

          meta = with pkgs.lib; {
            description = "Finestra flottante Picture-in-Picture con testi sincronizzati per Spotify";
            homepage = "https://github.com/genna2222/spotipip";
            license = licenses.mit;
            platforms = platforms.linux;
            mainProgram = "spotipip";
          };
        };
      in
      {
        packages.default = spotifyPipPkg;

        apps.default = flake-utils.lib.mkApp {
          drv = spotifyPipPkg;
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            pythonEnv
            pkgs.playerctl
            pkgs.xdg-utils
            pkgs.xorg.libX11
            pkgs.xorg.libXfixes
          ];
          shellHook = ''
            export QT_QPA_PLATFORM=xcb
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [ pkgs.xorg.libX11 pkgs.xorg.libXfixes ]}:$LD_LIBRARY_PATH"
          '';
        };
      }
    );
}