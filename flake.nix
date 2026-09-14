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
      # the arena renders with numpy, so it gets its own interpreter
      arenaPython = pkgs.python3.withPackages (ps: [ ps.numpy ]);
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
          cp scripts/arena.sh $out/bin/xyzide-arena
          cp scripts/brawl3d.py scripts/arena_audio.py $out/share/xyzide/
          cp scripts/xyzide.sh $out/bin/xyzide
          chmod +x $out/bin/*

          wrapProgram $out/bin/xyzide \
            --prefix PATH : "$out/bin" \
            --set XYZIDE_SHARE "$out/share/xyzide" \
            --set YAZI_CONFIG_HOME "$out/share/xyzide/configs/yazi" \
            --set LAYOUT_PATH "$out/share/xyzide/configs/layouts/default.kdl" \
            --set XYZIDE_OPENER "$out/bin/yazi-opener" \
            --set XYZIDE_ARENA "$out/bin/xyzide-arena"

          wrapProgram $out/bin/xyzide-arena \
            --set XYZIDE_PYTHON "${arenaPython}/bin/python3" \
            --set XYZIDE_ARENA_PY "$out/share/xyzide/brawl3d.py"
        '';
      };
    };
}
