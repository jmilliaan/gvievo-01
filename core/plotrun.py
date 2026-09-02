"""Per-run PNG for the auto control loop.

Renders on matplotlib, imported LAZILY. That matters: this module is pulled in
by runlog at startup, and matplotlib costs a second or two of import plus ~100 MB
of RSS - neither of which belongs in a process whose day job is holding a vehicle
on a line. Nothing is imported until a run actually ends and the render thread
asks for a picture.

Two other rules inherited from a sibling project's scars:

  * Agg backend, set before pyplot. There is no display on this machine.
  * The CSV is already on disk before this is called. A broken plotting install
    can therefore cost a picture but can never cost the data.

The figure shows five signals on two axes: commanded and actual left/right motor
speed on the left (r/min), cross-track error on the right (mm). Error is drawn
deliberately dominant - widest line, own colour-matched axis - because it is the
thing being tuned.
"""
import io

# Material 500, so the traces read the same as the reference plots from the
# sibling AGV. Commanded is saturated, actual is the same hue washed out, so a
# glance separates "what we asked for" from "what the wheels did".
C_CMD_L = "#1976D2"
C_CMD_R = "#388E3C"
C_ACT_L = "#90CAF9"
C_ACT_R = "#A5D6A7"
C_ERR = "#F44336"
C_TEXT = "#222222"
C_DIM = "#7a828c"
C_SHADE = "#f3ede1"

_STYLE_DONE = False


def _pyplot():
    """Import matplotlib on first use and apply the house style once."""
    global _STYLE_DONE
    import matplotlib
    matplotlib.use("Agg")               # headless; must precede pyplot
    import matplotlib.pyplot as plt
    if not _STYLE_DONE:
        plt.rcParams.update({
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#cccccc",
            "axes.labelcolor": C_TEXT,
            "text.color": C_TEXT,
            "xtick.color": C_DIM,
            "ytick.color": C_DIM,
            "font.size": 10,
            "axes.linewidth": 0.8,
            "lines.antialiased": True,
            "figure.autolayout": False,
        })
        _STYLE_DONE = True
    return plt


def _stats(rows):
    """One-line summary over the rows that were actually following the line.

    Restricted to state == "run" so the ramp-up and the stop do not drag the
    averages. Sampling here is uniform (one row per control tick, with dt in the
    row), so unlike a sensor-triggered recorder these means are unbiased.
    """
    import math
    run = [r for r in rows if r.get("state") == "run"]
    if not run:
        run = rows
    if not run:
        return ""
    e = [r["e_mm"] for r in run if r.get("e_mm") is not None]
    l = [r["n_l"] for r in run if r.get("n_l") is not None]
    r_ = [r["n_r"] for r in run if r.get("n_r") is not None]
    span = rows[-1]["t"] - rows[0]["t"] if len(rows) > 1 else 0.0
    parts = [f"Duration {span:.1f} s"]
    if e:
        rms = math.sqrt(sum(x * x for x in e) / len(e))
        parts.append(f"RMS {rms:.2f} mm")
        parts.append(f"Max {max(abs(x) for x in e):.0f} mm")
    if l and r_:
        parts.append(f"Avg L {sum(l) / len(l):.0f}")
        parts.append(f"Avg R {sum(r_) / len(r_):.0f} r/min")
    return "     ".join(parts)


def _decimate(rows, pw, t0, t1):
    """At most two rows per horizontal pixel, chosen as the min and max of the
    error trace in that column. Keeps the error envelope exact - a one-tick
    derivative spike still shows - while cutting a ten-minute run down to
    something that plots quickly."""
    if len(rows) <= 2 * pw or t1 <= t0:
        return rows
    buckets = {}
    for r in rows:
        b = int((r["t"] - t0) / (t1 - t0) * (pw - 1))
        lo, hi = buckets.get(b, (None, None))
        e = r.get("e_mm")
        if e is None:
            if lo is None:
                buckets[b] = (r, r)
            continue
        if lo is None or (lo.get("e_mm") is not None and e < lo["e_mm"]):
            lo = r
        if hi is None or (hi.get("e_mm") is not None and e > hi["e_mm"]):
            hi = r
        buckets[b] = (lo, hi)
    out = []
    for b in sorted(buckets):
        lo, hi = buckets[b]
        pair = sorted({id(lo): lo, id(hi): hi}.values(), key=lambda r: r["t"])
        out.extend(pair)
    return out


def _series(rows, key):
    """Column as floats with None -> NaN, so a gap breaks the line instead of
    being bridged by a straight segment that never happened."""
    out = []
    for r in rows:
        v = r.get(key)
        out.append(float("nan") if v is None else float(v))
    return out


def _shade_states(ax, rows):
    """Tint every stretch that was not 'run' and label it once."""
    i = 0
    while i < len(rows):
        st = rows[i].get("state")
        if st in (None, "", "run"):
            i += 1
            continue
        j = i
        while j + 1 < len(rows) and rows[j + 1].get("state") == st:
            j += 1
        ax.axvspan(rows[i]["t"], rows[j]["t"], color=C_SHADE, zorder=0)
        if rows[j]["t"] - rows[i]["t"] > (rows[-1]["t"] - rows[0]["t"]) * 0.02:
            ax.annotate(st, xy=(rows[i]["t"], 1.0), xycoords=("data", "axes fraction"),
                        xytext=(3, -12), textcoords="offset points",
                        fontsize=8, color="#a08a5a")
        i = j + 1


def render(rows, title="", subtitle="", width=1700, height=850,
           rpm_range=None, err_range=None, dpi=110):
    """rows: dicts with t, state, e_mm, n_l, n_r, rpm_l, rpm_r. -> PNG bytes.

    rpm_range / err_range are (lo, hi) pairs. Supplying them fixes the axes so
    runs are comparable by eye instead of each being scaled to its own data;
    traces then clip at the frame. Omit them and the axes fit the data.
    """
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)

    if not rows:
        ax.text(0.5, 0.5, "no data", ha="center", va="center",
                fontsize=16, color=C_DIM, transform=ax.transAxes)
        ax.set_axis_off()
        return _to_png(fig, plt, dpi)

    t0, t1 = rows[0]["t"], max(rows[-1]["t"], rows[0]["t"] + 1e-3)
    drawn = _decimate(rows, int(width), t0, t1)
    t = _series(drawn, "t")

    _shade_states(ax, rows)
    ax_e = ax.twinx()

    # Actual speed is polled at 5 Hz against a 50 Hz command, so it really is a
    # zero-order hold. steps-post draws what the data is rather than inventing
    # a smooth interpolation between samples the driver never reported.
    ax.plot(t, _series(drawn, "rpm_l"), color=C_ACT_L, lw=1.0,
            drawstyle="steps-post", label="actual L", zorder=2)
    ax.plot(t, _series(drawn, "rpm_r"), color=C_ACT_R, lw=1.0,
            drawstyle="steps-post", label="actual R", zorder=2)
    ax.plot(t, _series(drawn, "n_l"), color=C_CMD_L, lw=1.3,
            label="cmd L", zorder=3)
    ax.plot(t, _series(drawn, "n_r"), color=C_CMD_R, lw=1.3,
            label="cmd R", zorder=3)
    ax_e.plot(t, _series(drawn, "e_mm"), color=C_ERR, lw=1.7, alpha=0.95,
              label="error (mm)", zorder=4)

    ax.set_xlim(t0, t1)
    if rpm_range:
        ax.set_ylim(*rpm_range)
    if err_range:
        ax_e.set_ylim(*err_range)
    ax_e.axhline(0, color=C_ERR, lw=0.7, ls=":", alpha=0.6, zorder=1)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Wheel r/min")
    ax_e.set_ylabel("Tracking error (mm)", color=C_ERR)
    ax_e.tick_params(axis="y", colors=C_ERR)
    ax_e.spines["right"].set_color(C_ERR)
    ax.grid(True, ls="--", lw=0.6, alpha=0.35)
    ax.set_axisbelow(True)

    # Legend sits OUTSIDE the axes, on the title row, right-aligned against the
    # stats text on the left. Inside the frame it eventually covers data - this
    # run happens to have empty space at the top left, one starting at speed
    # would not.  Commanded first: it is the primary pair.
    by_label = {h.get_label(): h for h in ax.get_lines() + ax_e.get_lines()}
    order = ["cmd L", "cmd R", "actual L", "actual R", "error (mm)"]
    handles = [by_label[k] for k in order if k in by_label]
    ax.legend(handles, [h.get_label() for h in handles],
              loc="lower right", bbox_to_anchor=(1.0, 1.005),
              fontsize=9, ncol=5, frameon=False,
              handlelength=1.8, columnspacing=1.4)

    if title:
        fig.suptitle(title, fontsize=13, fontweight="semibold",
                     x=0.012, ha="left", y=0.985)
    ax.set_title(_stats(rows), fontsize=9.5, color=C_DIM, loc="left", pad=8)
    if subtitle:
        fig.text(0.012, 0.012, subtitle, fontsize=7.5, color=C_DIM, ha="left")

    fig.tight_layout(rect=(0, 0.028, 1, 0.94))
    return _to_png(fig, plt, dpi)


def _to_png(fig, plt, dpi):
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=dpi, facecolor=fig.get_facecolor())
    finally:
        plt.close(fig)          # figures are not garbage collected on their own
    return buf.getvalue()
