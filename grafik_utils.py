import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def grafik_olustur(figsize=(13, 6)):
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#161b22")
    for spine in ax.spines.values():
        spine.set_edgecolor("#30363d")
    ax.tick_params(colors="#8b949e")
    plt.xticks(color="#8b949e")
    plt.yticks(color="#8b949e")
    return fig, ax


def grafik_kaydet(fig) -> io.BytesIO:
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150,
                bbox_inches="tight", facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close()
    return buf
