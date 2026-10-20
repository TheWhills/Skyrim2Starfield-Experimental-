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
