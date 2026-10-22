_: {
  projectRootFile = "flake.nix";
  settings.excludes = [
    "docs/**/*.md"
    "**/index.md"
  ];
  programs.mdformat.enable = true;
  programs.black.enable = true;
  # Finish lint rewrites before formatting their output.
  programs.nixfmt = {
    enable = true;
    strict = true;
    priority = 3;
  };
  programs.deadnix.enable = true;
  programs.deadnix.priority = 1;
  programs.statix.enable = true;
  programs.statix.priority = 2;
  programs.actionlint.enable = true;
  programs.yamlfmt = {
    enable = true;
    settings.formatter.retain_line_breaks_single = true;
  };
}
