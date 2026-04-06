@echo off
if not exist out mkdir out
javac src\*.java -d out
echo Compilation done.
