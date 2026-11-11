{
  description = "Cambio card game";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.flake-utils.url = "github:numtide/flake-utils";

  outputs =
    { nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachSystem [ "x86_64-linux" "aarch64-linux" ] (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        packages.default = pkgs.python3Packages.buildPythonApplication {
          pname = "cambio";
          version = "0.1.0";
          src = ./.;
          pyproject = true;

          build-system = [ pkgs.python3Packages.setuptools ];
          dependencies = [ pkgs.python3Packages.pygame-ce ];
        };

        # the test output
        checks.default =
          pkgs.runCommand "cambio-tests"
            {

              #everything we need to run these pytest tests
              nativeBuildInputs = [
                pkgs.python3
                pkgs.python3Packages.pytest
                pkgs.python3Packages.pygame-ce
              ];
            }
            ''
              cp -r ${./.} tests
              chmod -R u+w tests
              cd tests

              python -m pytest && touch "$out"
            '';
      }
    );
}
