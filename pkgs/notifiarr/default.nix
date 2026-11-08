{
  lib,
  stdenvNoCC,
  fetchurl,
  gzip,
}:
let
  releases = {
    x86_64-linux = {
      arch = "amd64";
      hash = "sha256-cF+I7ZwAK8nMfkKbI3e8VjZYiZpnWXCQLBUR/ANb4mA=";
    };
    aarch64-linux = {
      arch = "arm64";
      hash = "sha256-Zdo4IPQv1XNjxMjRak3GUxfrvvvB3q4DIiBfCWo5Qw0=";
    };
  };
  release = releases.${stdenvNoCC.hostPlatform.system};
in
stdenvNoCC.mkDerivation rec {
  pname = "notifiarr";
  version = "0.10.0";
  src = fetchurl {
    url = "https://github.com/Notifiarr/notifiarr/releases/download/v${version}/notifiarr.${release.arch}.linux.gz";
    inherit (release) hash;
  };
  nativeBuildInputs = [ gzip ];
  dontUnpack = true;
  # Upstream's release executable is statically linked, including its web UI.
  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    gzip -dc $src > $out/bin/notifiarr
    chmod 755 $out/bin/notifiarr
    runHook postInstall
  '';
  meta = {
    description = "Notifiarr media application integration client";
    homepage = "https://github.com/Notifiarr/notifiarr";
    license = lib.licenses.mit;
    platforms = builtins.attrNames releases;
    mainProgram = "notifiarr";
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
}
