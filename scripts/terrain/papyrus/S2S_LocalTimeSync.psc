ScriptName S2S_LocalTimeSync extends Quest
{Skyrim2Starfield, 2026-11-13. Keeps the planet Nirn's local time (where its sun stands) equal to the game hour, the
clock NPC schedules run on. Owner's test: GetCurrentTime gave the UT hour while local time ran ~6 h ahead and slipped a
few minutes a day (the planet turns once per 24 h but also moves along its orbit). Every EverySeconds real seconds
(2026-11-13: a game-hour timer left a coc / landing unsynced for up to an hour) and on game load, only while the
player is on Nirn: if the two differ by more than Tolerance hours, SetLocalTime turns the planet to the game hour
(minus SunLagHours, 2026-11-20).}

Int Property PlanetID = 0x800 Auto Const                         ; Nirn's planet record (PNDT) in PlanetPlugin
String Property PlanetPlugin = "SkyrimTerrainTamriel_Mars.esm" Auto Const
Float Property EverySeconds = 10.0 Auto Const                    ; real seconds between checks (cheap when in step)
Float Property Tolerance = 0.05 Auto Const                       ; 3 minutes
; 2026-11-20 (owner: "the sun sets round 6-7PM or even 7-8PM, it gets sooo dark"): with the planet's axial tilt 0 the
; day is 12 hours all year (sun up at local 6:00, down at 18:00); the sun runs this many hours behind the game clock,
; so it rises at 6 + SunLagHours and sets at 18 + SunLagHours on the clock the schedules use
Float Property SunLagHours = 1.5 Auto Const

Event OnQuestInit()
    RegisterForRemoteEvent(Game.GetPlayer(), "OnPlayerLoadGame")
    Sync()
EndEvent

Event Actor.OnPlayerLoadGame(Actor akSender)
    Sync()
EndEvent

Event OnTimer(Int aiTimerID)
    Sync()
EndEvent

Function Sync()
    Planet nirn = Game.GetFormFromFile(PlanetID, PlanetPlugin) as Planet
    Planet here = Game.GetPlayer().GetCurrentPlanet()
    If nirn && here == nirn
        Float days = Utility.GetCurrentGameTime()
        Float hour = (days - Math.Floor(days)) * 24.0 - SunLagHours
        If hour < 0.0
            hour += 24.0
        EndIf
        Float diff = Math.Abs(Game.GetLocalTime() - hour)
        If diff > Tolerance && diff < 24.0 - Tolerance
            Debug.Trace("S2S_LocalTimeSync: local " + Game.GetLocalTime() + " -> game hour - lag " + hour)
            Game.SetLocalTime(hour)
        EndIf
    EndIf
    CancelTimer()
    StartTimer(EverySeconds)
EndFunction
