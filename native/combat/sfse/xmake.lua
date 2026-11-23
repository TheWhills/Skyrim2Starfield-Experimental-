-- S2SCombat: the Starfield (SFSE) side of the combat plugin (docs/armor/combat-plugin-spec.md, sfse/README.md).
-- Build on Windows with Visual Studio 2022 Build Tools and xmake 3:
--   git submodule update --init --recursive
--   cd native\combat\sfse
--   xmake f -m releasedbg
--   xmake
-- The game-independent core (../src, ../include) is compiled in; its tests run anywhere with CMake (../CMakeLists.txt).
set_xmakever("3.0.0")

includes("lib/commonlibsf")

set_project("S2SCombat")
set_version("0.1.0")
set_license("MIT")
set_languages("c++23")
set_warnings("allextra")

add_rules("mode.debug", "mode.releasedbg")
add_rules("plugin.vsxmake.autoupdate")

target("S2SCombat")
    add_rules("commonlibsf.plugin", {
        name = "S2SCombat",
        author = "Skyrim2Starfield",
        description = "Skyrim modded melee combat systems (MCO / BFCO input buffer, Payload Interpreter, TK Dodge, Key Utils stances) for Starfield"
    })

    add_files("src/**.cpp", "../src/*.cpp")
    add_headerfiles("src/**.h", "../include/s2s/*.h")
    add_includedirs("src", "../include")
    set_pcxxheader("src/pch.h")

-- S2SClash: the weapon clash (Cinematic Clash style standoff) as an add-on to S2SCombat (src/ClashApi.h). Needs
-- S2SCombat installed; S2SCombat works without it. Its own INI: S2SClash.ini.
target("S2SClash")
    add_rules("commonlibsf.plugin", {
        name = "S2SClash",
        author = "Skyrim2Starfield",
        description = "Weapon clash standoffs for S2SCombat (perfect block -> locked blades, mash attack)"
    })

    add_files("clash/**.cpp", "src/Game.cpp", "../src/*.cpp")
    add_headerfiles("clash/**.h", "src/Game.h", "src/ClashApi.h", "../include/s2s/*.h")
    add_includedirs("clash", "src", "../include")
    set_pcxxheader("src/pch.h")

-- S2SDodge: the dodge alone, standalone (sfse/dodge, s2s/dodge_only.h): the same controller as S2SCombat with every
-- other system off. Not built by a plain `xmake`: `xmake build S2SDodge`. Its INI: S2SDodge.ini. Switches itself off
-- when S2SCombat.dll is loaded (both would dodge).
target("S2SDodge")
    set_default(false)
    add_rules("commonlibsf.plugin", {
        name = "S2SDodge",
        author = "Skyrim2Starfield",
        description = "TK Dodge style dodging for Starfield (standalone; dodge animations through SAM)"
    })

    add_files("dodge/**.cpp", "src/Game.cpp", "../src/*.cpp")
    add_headerfiles("dodge/**.h", "src/Game.h", "../include/s2s/*.h")
    add_includedirs("dodge", "src", "../include")
    set_pcxxheader("src/pch.h")
