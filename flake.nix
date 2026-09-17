{
  description = "Spotify PiP Lyrics overlay per NixOS (GNOME Always-On-Top fix)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          pyqt6
          requests
        ]);

        spotifyPipPkg = pkgs.stdenv.mkDerivation {
          pname = "spotify-pip";
          version = "1.0.3";

          src = ./.;

          nativeBuildInputs = [ pkgs.makeWrapper ];

          installPhase = ''
            runHook preInstall

            mkdir -p $out/lib/spotify-pip
            cp spotify_pip.py $out/lib/spotify-pip/

            mkdir -p $out/bin
            makeWrapper ${pythonEnv}/bin/python $out/bin/spotify-pip \
              --add-flags "$out/lib/spotify-pip/spotify_pip.py" \
              --set QT_QPA_PLATFORM xcb \
              --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.playerctl pkgs.xdg-utils ]}

            mkdir -p $out/share/applications
            cp spotipip $out/share/applications/

            runHook postInstall
          '';

          meta = with pkgs.lib; {
            description = "Finestra flottante Picture-in-Picture con testi sincronizzati per Spotify";
            homepage = "https://github.com/user/spotify-pip";
            license = licenses.mit;
            platforms = platforms.linux;
            mainProgram = "spotify-pip";
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
          ];
          shellHook = ''
            export QT_QPA_PLATFORM=xcb
          '';
        };
      }
    );
}