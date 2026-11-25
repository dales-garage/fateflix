{
  lib,
  stdenv,
  fetchurl,
  autoPatchelfHook,
  makeWrapper,
  icu,
  openssl,
  zlib,
  curl,
  krb5,
  lttng-ust_2_12,
}:
let
  release = builtins.fromJSON (builtins.readFile ./sources.json);
  source = release.sources.${stdenv.hostPlatform.system};
in
stdenv.mkDerivation {
  pname = "prowlarr-upstream";
  inherit (release) version;
  src = fetchurl source;
  nativeBuildInputs = [
    autoPatchelfHook
    makeWrapper
  ];
  buildInputs = [
    stdenv.cc.cc.lib
    lttng-ust_2_12
  ];
  dontBuild = true;
  # Stripping PE assemblies corrupts the bundled .NET ReadyToRun images.
  dontStrip = true;
  installPhase = ''
        runHook preInstall
        mkdir -p "$out/lib/prowlarr" "$out/bin"
        cp -a . "$out/lib/prowlarr/"
        makeWrapper "$out/lib/prowlarr/Prowlarr" "$out/bin/Prowlarr" \
          --prefix LD_LIBRARY_PATH : ${
            lib.makeLibraryPath [
              icu
              openssl
              zlib
              curl
              krb5
            ]
          }
        cat > "$out/lib/package_info" <<EOF
    PackageAuthor=FateFlix
    PackageVersion=$version
    UpdateMethod=External
    UpdateMethodMessage=Update the locked FateFlix configuration to upgrade Prowlarr.
    EOF
        runHook postInstall
  '';
  # The official archives include the matching self-contained .NET runtime.
  # autoPatchelf repairs ELF loaders/RPATHs; these libraries are loaded via dlopen.
  meta = {
    description = "Official stable Prowlarr release with its upstream .NET runtime";
    homepage = "https://prowlarr.com";
    changelog = "https://github.com/Prowlarr/Prowlarr/releases/tag/v${release.version}";
    license = lib.licenses.gpl3Only;
    platforms = builtins.attrNames release.sources;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    mainProgram = "Prowlarr";
  };
}
