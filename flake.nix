{
  description = "Lyripip - Music PiP Lyrics overlay per NixOS (Spotify & Feishin)";

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

        lyripipPkg = pkgs.stdenv.mkDerivation {
          pname = "lyripip";
          version = "1.0.4";

          src = ./.;

          nativeBuildInputs = [ pkgs.makeWrapper ];

          installPhase = ''
            runHook preInstall
            mkdir -p $out/lib/lyripip
            cp spotify_pip.py $out/lib/lyripip/
            cp lyripip.png $out/lib/lyripip/
            cp lyripip.svg $out/lib/lyripip/

            mkdir -p $out/bin
            makeWrapper ${pythonEnv}/bin/python $out/bin/lyripip \
              --add-flags "$out/lib/lyripip/spotify_pip.py" \
              --set QT_QPA_PLATFORM xcb \
              --prefix XDG_DATA_DIRS : "$out/share" \
              --prefix PATH : ${
                pkgs.lib.makeBinPath [
                  pkgs.playerctl
                  pkgs.xdg-utils
                ]
              }

            mkdir -p $out/share/applications
            cp lyripip.desktop $out/share/applications/

            mkdir -p $out/share/icons/hicolor/scalable/apps
            cp lyripip.svg $out/share/icons/hicolor/scalable/apps/lyripip.svg

            mkdir -p $out/share/icons/hicolor/256x256/apps
            cp lyripip.png $out/share/icons/hicolor/256x256/apps/lyripip.png
            runHook postInstall
          '';

          meta = with pkgs.lib; {
            description = "Finestra flottante Picture-in-Picture con testi sincronizzati per Spotify e Feishin";
            homepage = "https://github.com/genna2222/spotipip";
            license = licenses.mit;
            platforms = platforms.linux;
            mainProgram = "lyripip";
          };
        };
      in
      {
        packages.default = lyripipPkg;

        apps.default = flake-utils.lib.mkApp {
          drv = lyripipPkg;
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            pythonEnv
            pkgs.playerctl
            pkgs.xdg-utils
          ];
          shellHook = ''
            export QT_QPA_PLATFORM=xcb
          '';
        };
      }
    );
}