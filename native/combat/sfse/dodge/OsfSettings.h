// OSF Settings (Nexus 18326, github.com/ozooma10/osf-settings): the part of its native service S2SDodge uses, declared
// here for interoperability rather than including its SDK header (GPL-3.0; S2SDodge keeps its own license). Only the
// calls S2SDodge makes are given names; the slot order and the ABI facts follow the service's published contract
// (ABI 1.0: export OSFSettings_RequestAPI in OSFSettings.dll, interface slots in this order, no virtual destructor).
// OSF Settings is optional: when OSFSettings.dll is not loaded, Request() returns nullptr and S2SDodge keeps its INI key.
#pragma once

#include <cstdint>

namespace s2s::dodge::osf {

inline constexpr std::uint32_t kVersion = 0x00010000u;          // ABI major.minor 1.0
inline constexpr wchar_t kModule[] = L"OSFSettings.dll";
inline constexpr char kRequestExport[] = "OSFSettings_RequestAPI";

enum class Status : std::uint32_t { Ok = 0, NotReady = 1 };      // other values: failures (logged as numbers)

using HotkeyFn = void (*)(const char* mod, const char* id, void* context) noexcept;   // inline, during input handling
using AcquireFn = void* (*)(std::uint32_t version, std::uint32_t* outVersion) noexcept;

// Slots before RegisterHotkey are declared only to keep the order; S2SDodge does not call them.
struct ISettings {
    virtual bool IsReady() noexcept = 0;
    virtual Status Slot01() noexcept = 0;   // GetBool
    virtual Status Slot02() noexcept = 0;   // GetInt
    virtual Status Slot03() noexcept = 0;   // GetFloat
    virtual Status Slot04() noexcept = 0;   // GetEnum
    virtual Status Slot05() noexcept = 0;   // SetBool
    virtual Status Slot06() noexcept = 0;   // SetInt
    virtual Status Slot07() noexcept = 0;   // SetFloat
    virtual Status Slot08() noexcept = 0;   // SetEnum
    virtual Status Slot09() noexcept = 0;   // Reset
    virtual Status Slot10() noexcept = 0;   // ResetMod
    virtual Status Slot11() noexcept = 0;   // Subscribe
    virtual Status Slot12() noexcept = 0;   // Unsubscribe
    virtual Status Slot13() noexcept = 0;   // GetKey
    virtual Status Slot14() noexcept = 0;   // SetKey
    virtual Status Slot15() noexcept = 0;   // AcquireHotkeyBlock
    virtual Status Slot16() noexcept = 0;   // ReleaseHotkeyBlock
    // A hotkey declared in the mod's schema (SFSE\Plugins\OSF\Settings\schemas\<mod>.json); register at kPostLoad.
    virtual Status RegisterHotkey(const char* mod, const char* id, HotkeyFn callback, void* context) noexcept = 0;

protected:
    ~ISettings() = default;
};

// The service, or nullptr when OSF Settings is not loaded or speaks another major ABI.
inline ISettings* Request() noexcept {
    const auto module = REX::W32::GetModuleHandleW(kModule);
    if (!module) return nullptr;
    const auto fn = reinterpret_cast<AcquireFn>(REX::W32::GetProcAddress(module, kRequestExport));
    if (!fn) return nullptr;
    std::uint32_t actual = 0;
    auto* api = static_cast<ISettings*>(fn(kVersion, &actual));
    const bool compatible = (actual >> 16) == (kVersion >> 16) && (actual & 0xFFFFu) >= (kVersion & 0xFFFFu);
    return compatible ? api : nullptr;
}

}  // namespace s2s::dodge::osf
