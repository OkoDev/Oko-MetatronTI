Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('Microsoft Irina Desktop')
$s.Speak("Vopros po Fib TP zakryt. TSL ostaetsya osnovoy. Discussion obnovlen.")
