@echo off

dotnet publish UniApkBuilder/UniApkBuilder/UniApkBuilder.csproj -p:PublishProfile=Properties\PublishProfiles\FolderProfile.pubxml

echo.

docker build -t mghcool/uni-apk-builder .

pause