import re
import uuid
from pathlib import Path

import yt_dlp
from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / 'downloads'
DOWNLOAD_DIR.mkdir(exist_ok=True)


def extract_info_with_fallback(video_url):
    base_options = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extract_flat': False,
    }

    client_variants = [
        {'youtube': ['player_client=web']},
        {'youtube': ['player_client=android']},
        {'youtube': ['player_client=tv_embedded']},
        {},
    ]

    last_error = None
    for variant in client_variants:
        options = dict(base_options)
        if variant:
            options['extractor_args'] = variant
        try:
            info = yt_dlp.YoutubeDL(options).extract_info(video_url, download=False)
            return info
        except Exception as exc:  # pragma: no cover - runtime-specific fallback
            last_error = exc

    if last_error is not None:
        raise last_error

    raise ValueError('No metadata was returned for this link.')


@app.route('/')
def index():
    return render_template('index.html')


@app.get('/health')
def health():
    return jsonify({'status': 'ok'})


@app.post('/api/download')
def download_video():
    payload = request.get_json(silent=True) or {}
    video_url = (payload.get('url') or request.form.get('url') or '').strip()
    if not video_url:
        return jsonify({'status': 'error', 'message': 'No video URL provided.'}), 400

    session_id = uuid.uuid4().hex[:8]
    session_dir = DOWNLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    safe_title = 'downloaded_video'
    try:
        info = extract_info_with_fallback(video_url)
        if isinstance(info, dict) and 'entries' in info and info['entries']:
            info = info['entries'][0]
        if not isinstance(info, dict):
            raise ValueError('No metadata was returned for this link.')

        title = info.get('title') or 'downloaded_video'
        safe_title = re.sub(r'[^A-Za-z0-9_. -]', '', title) or 'downloaded_video'
        channel = info.get('channel') or 'Unknown channel'
        duration = info.get('duration_string') or '0:00'
        thumbnail = info.get('thumbnail') or ''

        options = {
            'outtmpl': str(session_dir / f'{safe_title}.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'format': 'best',
            'socket_timeout': 30,
            'ignoreerrors': False,
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([video_url])
    except Exception as exc:
        return jsonify({'status': 'error', 'message': f'Failed to download: {exc}'}), 500

    downloaded_file = None
    for path in sorted(session_dir.rglob('*'), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_file() and path.suffix.lower() in {'.mp4', '.m4a', '.mp3', '.webm', '.mov', '.mkv'}:
            downloaded_file = path
            break

    if not downloaded_file:
        return jsonify({'status': 'error', 'message': 'No download was created.'}), 500

    file_name = secure_filename(downloaded_file.name)
    return jsonify({
        'status': 'success',
        'title': title,
        'channel': channel,
        'duration': duration,
        'thumbnail': thumbnail,
        'download_url': f'/api/file/{session_id}/{file_name}',
    })


@app.route('/api/file/<session_id>/<path:filename>')
def serve_download(session_id, filename):
    safe_dir = DOWNLOAD_DIR / session_id
    return send_from_directory(safe_dir, filename, as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
