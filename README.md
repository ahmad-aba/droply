# Droply

Droply is a self-hosted web app for saving videos, audio, images, PDFs, and other files you own or have permission to download. It uses `yt-dlp`, which supports a large range of public media sites, plus direct file links.

## Run it

You need Python 3.10+.

```powershell
python -m pip install -r requirements.txt
python app.py
```

Then open [http://127.0.0.1:5050](http://127.0.0.1:5050).

The app writes completed files into `downloads/` and also provides a Save file button in the browser. Those files are automatically cleared from the in-memory task list after six hours; you can delete anything you no longer need from the folder.

## Best quality and MP3 conversion

Droply works without FFmpeg by choosing compatible single-file streams. Installing FFmpeg enables the downloader to merge higher-resolution video/audio streams and convert audio downloads to MP3.

## Supported sources

The underlying download engine supports thousands of public sites. The interface highlights YouTube, Instagram, Facebook, TikTok, Pinterest, Reddit, X, Vimeo, SoundCloud, Twitch, Dailymotion, LinkedIn, Snapchat, Threads, VK, Rumble, Bilibili, Bandcamp, BBC iPlayer, TED, Archive.org, Streamable, and direct image/PDF/file URLs. A source may limit downloads because of its own access rules, region, login, or licensing.

## Responsible use

Only save content that you own or are otherwise authorized to download. This project does not bypass passwords, paid access, DRM, or platform controls.
