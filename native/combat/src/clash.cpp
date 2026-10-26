#include "s2s/clash.h"

#include <algorithm>
#include <cstdlib>

namespace s2s::combat {
namespace {

bool read_double(const std::string& v, double& out) {
    if (v.empty()) return false;
    char* end = nullptr;
    const double d = std::strtod(v.c_str(), &end);
    if (end == v.c_str() || *end != '\0') return false;
    out = d;
    return true;
}

bool read_bool(const std::string& v, bool& out) {
    if (v != "0" && v != "1") return false;
    out = v == "1";
    return true;
}

Command actor_events(std::uint32_t target, const std::string& events) {
    Command c{Command::Kind::ActorEvents, events};
    c.target = target;
    return c;
}

Command notify(const std::string& text) { return Command{Command::Kind::Notify, text}; }

}  // namespace

ClashConfig parse_clash_config(std::string_view ini, std::vector<std::string>* problems) {
    ClashConfig c;
    for (const auto& [k, v] : ini_section(ini, "Clash")) {
        bool ok = true;
        double d = 0.0;
        if (k == "benabled") ok = read_bool(v, c.enabled);
        else if (k == "bonperfectblock") ok = read_bool(v, c.on_perfect_block);
        else if (k == "ftriggerchance") ok = read_double(v, c.trigger_chance);
        else if (k == "fcooldownseconds") ok = read_double(v, c.cooldown);
        else if (k == "fmaxstartdistance") ok = read_double(v, c.max_start_distance);
        else if (k == "fduration") ok = read_double(v, c.duration) && c.duration > 0.0;
        else if (k == "fpressgain") ok = read_double(v, c.press_gain);
        else if (k == "imode") {
            ok = read_double(v, d) && (d == 0.0 || d == 1.0 || d == 2.0);
            if (ok) c.mode = static_cast<int>(d);
        }
        else if (k == "feasypressespersecond") ok = read_double(v, c.presses_per_second[0]);
        else if (k == "fnormalpressespersecond") ok = read_double(v, c.presses_per_second[1]);
        else if (k == "fhardpressespersecond") ok = read_double(v, c.presses_per_second[2]);
        else if (k == "bholdtomash") ok = read_bool(v, c.hold_to_mash);
        else if (k == "itimeoutresolution") {
            ok = read_double(v, d) && (d == 0.0 || d == 1.0);
            if (ok) c.timeout_resolution = static_cast<int>(d);
        }
        else if (k == "fclashdistance") ok = read_double(v, c.clash_distance);
        else if (k == "fgracetime") ok = read_double(v, c.grace_time);
        else if (k == "fcamerayaw") ok = read_double(v, c.camera_yaw);
        else if (k == "fcamerapitch") ok = read_double(v, c.camera_pitch);
        else if (k == "sguardevents") c.guard_events = v;
        else if (k == "sinterruptevents") c.interrupt_events = v;
        else if (k == "sstaggervariable") c.stagger_variable = v;
        else if (k == "floserstaggermagnitude") ok = read_double(v, c.loser_magnitude);
        else if (k == "fdrawstaggermagnitude") ok = read_double(v, c.draw_magnitude);
        else if (k == "fguardinterval") ok = read_double(v, c.guard_interval);
        else if (k == "sguardvariable") c.guard_variable = v;
        else if (k == "sloserevents") c.loser_events = v;
        else if (k == "swinnerevents") c.winner_events = v;
        else if (k == "sdrawevents") c.draw_events = v;
        else if (k == "sendevents") c.end_events = v;
        else if (k == "bmessages") ok = read_bool(v, c.messages);
        else if (k == "sstart") c.start_message = v;
        else if (k == "sstarthold") c.start_message_hold = v;
        else if (k == "swin") c.win_message = v;
        else if (k == "slose") c.lose_message = v;
        else if (k == "sdraw") c.draw_message = v;
        else if (k == "swinning") c.winning_message = v;
        else if (k == "slosing") c.losing_message = v;
        else if (k == "bshakeonpress") ok = read_bool(v, c.shake_on_press);
        else if (k == "fshakestrength") {
            ok = read_double(v, d);
            if (ok) c.shake_strength = static_cast<float>(d);
        }
        else if (k == "fsparkinterval") ok = read_double(v, c.spark_interval);
        else if (k == "bplaceopponent") ok = read_bool(v, c.place_opponent);
        else if (k == "brestrainopponent") ok = read_bool(v, c.restrain_opponent);
        else if (k == "blockcamera") ok = read_bool(v, c.lock_camera);
        else if (k == "bblockmovement") ok = read_bool(v, c.block_movement);
        else if (k == "bghostplayer") ok = read_bool(v, c.ghost_player);
        else if (k == "bfaceeachother") ok = read_bool(v, c.face_each_other);
        else if (k == "bforceclashonhit") ok = read_bool(v, c.force_on_hit);
        else ok = false;
        if (!ok && problems) problems->push_back("[Clash] " + k + " = " + v + ": not understood, default kept");
    }
    return c;
}

bool take_perfect_block(std::vector<Command>& cmds, std::uint32_t attacker) {
    if (attacker == 0) return false;
    const auto before = cmds.size();
    cmds.erase(std::remove_if(cmds.begin(), cmds.end(),
                              [&](const Command& c) {
                                  return c.kind == Command::Kind::ActorEvents && c.target == attacker;
                              }),
               cmds.end());
    return cmds.size() != before;
}

double Clash::push_rate() const {
    const int m = std::clamp(cfg_.mode, 0, 2);
    return cfg_.press_gain * cfg_.presses_per_second[m];
}

bool Clash::can_start(double t, double roll) const {
    return cfg_.enabled && !active_ && t - ended_ >= cfg_.cooldown && roll < cfg_.trigger_chance;
}

void Clash::guard(std::vector<Command>& out, double t) {
    if (!cfg_.guard_events.empty())
        for (std::uint32_t who : {opponent_, std::uint32_t{0x14}}) {
            Command g{Command::Kind::Guard, cfg_.guard_events};
            g.target = who;
            g.extra = cfg_.interrupt_events;
            out.push_back(g);
        }
    // During the grace time the guard is checked more often: the opponent's own reaction to the hit (recoil, the rest
    // of its attack) can start just after the clash and drop the guard (owner's run 2026-10-26). The game side skips
    // whoever is already blocking, so a held guard is left alone.
    const bool early = t - started_ < cfg_.grace_time;
    next_guard_ = t + (early ? std::min(cfg_.guard_interval, 0.1) : cfg_.guard_interval);
}

std::vector<Command> Clash::start(std::uint32_t opponent, double t, double roll) {
    std::vector<Command> out;
    if (opponent == 0 || !can_start(t, roll)) return out;
    active_ = true;
    held_ = false;
    opponent_ = opponent;
    meter_ = 0.5;
    started_ = last_tick_ = t;
    next_spark_ = t;
    zone_ = 0;
    presses_ = 0;
    outcome_ = Outcome::None;
    Command begin{Command::Kind::ClashBegin};
    begin.target = opponent;
    begin.amount = static_cast<float>(cfg_.clash_distance);
    out.push_back(begin);
    if (!cfg_.guard_variable.empty()) {
        Command v{Command::Kind::ActorVariable};
        v.target = opponent;
        v.variable = {VariableSet::Type::Int, cfg_.guard_variable, 1.0};
        out.push_back(v);
    }
    guard(out, t);
    if (cfg_.messages) {
        const auto& m = cfg_.hold_to_mash ? cfg_.start_message_hold : cfg_.start_message;
        if (!m.empty()) out.push_back(notify(m));
    }
    return out;
}

std::vector<Command> Clash::on_attack(bool down, double t) {
    std::vector<Command> out;
    if (!active_) return out;
    if (cfg_.hold_to_mash) {
        // the held time is added in tick; a release just stops it
        if (down != held_) {
            auto ticked = tick(t);               // count the hold up to now at the old state
            out.insert(out.end(), ticked.begin(), ticked.end());
            held_ = down;
        }
        return out;
    }
    if (!down) return out;
    if (t - started_ < cfg_.grace_time) return out;   // the lock is still forming: the meter does not move yet
    ++presses_;
    out = tick(t);                               // the opponent's push up to now (may end the clash)
    if (!active_) return out;
    if (cfg_.shake_on_press && cfg_.shake_strength > 0.0f) {
        Command s{Command::Kind::Shake};
        s.amount = cfg_.shake_strength;
        s.dx = 100;
        out.push_back(s);
    }
    meter_ = std::min(1.0, meter_ + cfg_.press_gain);
    if (meter_ >= 1.0) {                         // a press that fills the meter ends the clash at once
        auto done = finish(Outcome::Win, t);
        out.insert(out.end(), done.begin(), done.end());
    }
    return out;
}

std::vector<Command> Clash::tick(double t) {
    std::vector<Command> out;
    if (!active_) return out;
    // the push starts after the grace time
    const double from = std::max(last_tick_, started_ + cfg_.grace_time);
    const double dt = std::max(0.0, t - from);
    last_tick_ = t;
    meter_ -= push_rate() * dt;
    if (cfg_.hold_to_mash && held_) meter_ += push_rate() * dt;     // a hold exactly matches an equal opponent
    meter_ = std::clamp(meter_, 0.0, 1.0);
    if (meter_ >= 1.0) return finish(Outcome::Win, t);
    if (meter_ <= 0.0) return finish(Outcome::Lose, t);
    if (t - started_ >= cfg_.duration) {
        Outcome o = Outcome::Draw;
        if (cfg_.timeout_resolution == 1 && meter_ != 0.5) o = meter_ > 0.5 ? Outcome::Win : Outcome::Lose;
        return finish(o, t);
    }
    const int zone = meter_ > 0.75 ? 1 : meter_ < 0.25 ? -1 : 0;
    if (zone != zone_) {
        if (cfg_.messages && zone == 1 && !cfg_.winning_message.empty()) out.push_back(notify(cfg_.winning_message));
        if (cfg_.messages && zone == -1 && !cfg_.losing_message.empty()) out.push_back(notify(cfg_.losing_message));
        zone_ = zone;
    }
    if (t >= next_guard_) guard(out, t);
    if (cfg_.spark_interval > 0.0 && t >= next_spark_) {
        Command s{Command::Kind::Spark};
        s.target = opponent_;
        out.push_back(s);
        next_spark_ = t + cfg_.spark_interval;
    }
    return out;
}

std::vector<Command> Clash::abort(double t, std::string_view why) {
    if (!active_) return {};
    auto out = finish(Outcome::Abort, t);
    out.insert(out.begin(), Command{Command::Kind::Log, "clash aborted: " + std::string(why)});
    return out;
}

std::vector<Command> Clash::finish(Outcome o, double t) {
    std::vector<Command> out;
    active_ = false;
    held_ = false;
    ended_ = t;
    outcome_ = o;
    if (!cfg_.guard_variable.empty()) {
        Command v{Command::Kind::ActorVariable};
        v.target = opponent_;
        v.variable = {VariableSet::Type::Int, cfg_.guard_variable, 0.0};
        out.push_back(v);
    }
    const char* name = o == Outcome::Win ? "win" : o == Outcome::Lose ? "lose" : o == Outcome::Draw ? "draw" : "abort";
    Command end{Command::Kind::ClashEnd, name};
    end.target = opponent_;
    out.push_back(end);
    if (!cfg_.end_events.empty()) out.emplace_back(Command::Kind::SendEvent, cfg_.end_events);
    // the player is form 0x14 for ActorEvents
    constexpr std::uint32_t player = 0x14;
    auto magnitude = [&](std::uint32_t who, double m) {
        if (cfg_.stagger_variable.empty()) return;
        Command v{Command::Kind::ActorVariable};
        v.target = who;
        v.variable = {VariableSet::Type::Float, cfg_.stagger_variable, m};
        out.push_back(v);
    };
    auto events = [&](std::uint32_t who, const std::string& e) {
        if (!e.empty()) out.push_back(actor_events(who, e));
    };
    std::string message;
    switch (o) {
        case Outcome::Win:
            magnitude(opponent_, cfg_.loser_magnitude);
            events(opponent_, cfg_.loser_events);
            events(player, cfg_.winner_events);
            message = cfg_.win_message;
            break;
        case Outcome::Lose:
            magnitude(player, cfg_.loser_magnitude);
            events(player, cfg_.loser_events);
            events(opponent_, cfg_.winner_events);
            message = cfg_.lose_message;
            break;
        case Outcome::Draw:
            magnitude(opponent_, cfg_.draw_magnitude);
            magnitude(player, cfg_.draw_magnitude);
            events(opponent_, cfg_.draw_events);
            events(player, cfg_.draw_events);
            message = cfg_.draw_message;
            break;
        default: break;
    }
    if (cfg_.messages && !message.empty()) out.push_back(notify(message));
    return out;
}

}  // namespace s2s::combat
