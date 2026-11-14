@echo off
python broadband_engine.py --input-dir . --output-dir output
python -m unittest -v test_engine.py
pause
