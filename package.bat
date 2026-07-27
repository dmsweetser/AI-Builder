
@echo off
echo Packaging AI-Builder...
pip install pyinstaller
pyinstaller --onefile --windowed --name ai-builder ai_builder.py ^
    --add-data "templates;templates" ^
    --add-data "base_config.xml;." ^
    --add-data "instructions.txt;."
echo Packaging complete. Output is in the dist/ directory.
pause
