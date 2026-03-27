Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('Microsoft Irina Desktop')
$s.Speak('TR nol odin zavershon. STG SHORT plus devyanosto sem R blizhno k TP. ENA i JUP ekstremalny oversold. Win Rate pyatnadtsat protsent za sem dney. Prioritet DEV vosemdesyat pyat.')
