# 🔴 Live Playlist Updater

Automatically generates and updates an M3U playlist of live streams every 10 minutes using GitHub Actions.

## How It Works

1. **`models.txt`** — Add model usernames separated by commas
2. **GitHub Action** runs every 10 minutes
3. **Script checks** which models are currently live
4. **`playlist.m3u`** is updated with only live streams
5. Changes are auto-committed to the repo

## Setup

### 1. Fork/Clone this repo

### 2. Edit `models.txt`

Add model names separated by commas:
