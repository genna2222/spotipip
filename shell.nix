{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  packages = with pkgs; [
    playerctl
    (python3.withPackages (ps: with ps; [
      pyqt6
      requests
    ]))
  ];
}