#!/usr/bin/env bash
# Cut the two hero takes into one clip.
#
# Every edit here is either a cut, a hold, or a speed-up that is labelled on
# screen. Nothing is re-ordered and no output is altered, with one exception:
# a rotating Claude Code promo row ("earn CA$15 in credits") is painted over
# with the background colour while it is on screen. It is account-specific
# and unrelated to the demo.
#
# The timestamps below come from this particular take (freezedetect and
# signalstats on hero-a.mp4). A new take needs new numbers.
set -euo pipefail
cd "$(dirname "$0")/out"

FONT="C\\:/Windows/Fonts/consolab.ttf"
BADGE="fontfile='$FONT':fontsize=22:fontcolor=0x12151a:box=1:boxcolor=0x34e39b:boxborderw=8:x=w-tw-36:y=28"

# hero-a: realtime until Claude starts thinking; thinking at 8x; the edit
# and its verification at 3x; then hold Claude's summary so it can be read.
THINK_START=12.0
THINK_END=45.2
WORK_END=85.5
PROMO_UNTIL=51.32      # the promo row scrolls off screen here
# hero-b: hold "pblame attached 1 prompt to this commit" before the cut.
ATTACH_AT=5.0

ffmpeg -v error -y -i hero-a.mp4 -i hero-b.mp4 -filter_complex "
[0:v]drawbox=x=0:y=114:w=1280:h=38:color=0x12151b:t=fill:enable='lt(t,$PROMO_UNTIL)',split=3[a][b][c];
[a]trim=0:$THINK_START,setpts=PTS-STARTPTS[s1];
[b]trim=$THINK_START:$THINK_END,setpts=(PTS-STARTPTS)/8,drawtext=text='8x':$BADGE[s2];
[c]trim=$THINK_END:$WORK_END,setpts=(PTS-STARTPTS)/3,tpad=stop_mode=clone:stop_duration=3.5,
   drawtext=text='3x':$BADGE:enable='lt(t,($WORK_END-$THINK_END)/3)'[s3];
[1:v]split=2[d][e];
[d]trim=0:$ATTACH_AT,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=1.5[b1];
[e]trim=$ATTACH_AT,setpts=PTS-STARTPTS[b2];
[s1][s2][s3][b1][b2]concat=n=5:v=1:a=0,fps=30,format=yuv420p[v]
" -map "[v]" -c:v libx264 -crf 22 -preset slow -movflags +faststart hero.mp4

ffprobe -v error -show_entries format=duration,size -of default=nw=1 hero.mp4
