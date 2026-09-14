import io

with io.open('main.js', 'rb') as f:
    js = f.read()

audio_code = b'''

// === AUDIO PLAYER ===
(function() {
  const audio = new Audio('./001.MP3');
  audio.preload = 'auto';
  let playing = false;

  function fmt(t) {
    if (!isFinite(t)) return '0:00';
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function findTimeEl() {
    return document.querySelector('.player-time')
        || document.querySelector('.voice-player-time')
        || Array.from(document.querySelectorAll('span,div')).find(function(el) {
             return /^\\d+:\\d+\\s*\\/\\s*\\d+:\\d+$/.test(el.textContent.trim());
           });
  }

  function findProgressEl() {
    return document.querySelector('.player-fill')
        || document.querySelector('.player-progress-bar')
        || document.querySelector('.player-progress > div');
  }

  function update() {
    const timeEl = findTimeEl();
    if (timeEl) timeEl.textContent = fmt(audio.currentTime) + ' / ' + fmt(audio.duration);
    const bar = findProgressEl();
    if (bar && audio.duration > 0) bar.style.width = ((audio.currentTime / audio.duration) * 100) + '%';
  }

  audio.addEventListener('timeupdate', update);
  audio.addEventListener('loadedmetadata', update);

  audio.addEventListener('ended', function() {
    playing = false;
  });

  document.addEventListener('click', function(e) {
    const playBtn = e.target.closest('.btn-play');
    const rewBtn = e.target.closest('.btn-rew');
    const ffBtn = e.target.closest('.btn-ff');

    if (playBtn) {
      if (playing) {
        audio.pause();
        playing = false;
      } else {
        audio.play().then(function(){ playing = true; })
          .catch(function(err){ console.error('[AUDIO] play failed:', err); });
      }
    }
    if (rewBtn) audio.currentTime = Math.max(0, audio.currentTime - 10);
    if (ffBtn) audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 10);
  });

  console.log('[AUDIO] 001.MP3 ready');
})();
'''

if b'AUDIO PLAYER' not in js:
    with io.open('main.js', 'wb') as f:
        f.write(js + audio_code)
    print('OK - audio player added')
else:
    print('audio player already in main.js')
