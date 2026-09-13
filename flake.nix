{
  description = "Xyzide: scalable terminal IDE";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      packages.${system}.default = pkgs.stdenv.mkDerivation {
        pname = "xyzide";
        version = "1.0.0";

        src = ./.;

        nativeBuildInputs = [ pkgs.makeWrapper ];

        installPhase = ''
          mkdir -p $out/bin $out/share/xyzide
          cp -r configs $out/share/xyzide/
          cp scripts/yazi-opener.sh $out/bin/yazi-opener
          cp scripts/xyzide.sh $out/bin/xyzide
          chmod +x $out/bin/*

          wrapProgram $out/bin/xyzide \
            --prefix PATH : "$out/bin" \
            --set XYZIDE_SHARE "$out/share/xyzide" \
            --set YAZI_CONFIG_HOME "$out/share/xyzide/configs/yazi" \
            --set LAYOUT_PATH "$out/share/xyzide/configs/layouts/default.kdl" \
            --set XYZIDE_OPENER "$out/bin/yazi-opener"
        '';
      };
    };
}
