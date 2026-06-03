# Record the README demo GIF with VHS (https://github.com/charmbracelet/vhs):
#   vhs docs/demo.tape
# Requires a working .env with a model key in the recording directory.

Output docs/demo.gif

Set FontSize 16
Set Width 1100
Set Height 700
Set Theme "Catppuccin Mocha"
Set Padding 18
Set TypingSpeed 60ms

Type "prd-to-readout init"
Enter
Sleep 1500

Type "prd-to-readout run prd.md"
Enter
Sleep 18s
