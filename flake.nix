{
  description = "Xyzide: scalable terminal IDE";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        runtimeDeps = [
          pkgs.zellij
          pkgs.yazi

          # yazi preview deps
          pkgs._7zz
          pkgs.jq
          pkgs.poppler-utils
          pkgs.resvg
          pkgs.ffmpeg
          pkgs.imagemagick
        ];
      in
      {
        packages.default = pkgs.stdenv.mkDerivation {
          pname = "xyzide";
          version = "1.0.0";

          src = ./.;

          nativeBuildInputs = [ pkgs.makeWrapper ];

          installPhase = ''
            mkdir -p $out/bin $out/share/xyzide
            cp -r configs $out/share/xyzide/
            cp -r scripts $out/share/xyzide/
            chmod +x $out/share/xyzide/scripts/*.sh

            makeWrapper $out/share/xyzide/scripts/xyzide.sh $out/bin/xyzide \
              --prefix PATH : "${pkgs.lib.makeBinPath runtimeDeps}" \
              --set XYZ_SHARE "$out/share/xyzide"
          '';
        };
      }
    );
}
