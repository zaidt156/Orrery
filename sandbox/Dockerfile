# Orrery code-execution sandbox: a locked-down Python image that turns model-written
# code into real files of any type. Run with --network=none, resource caps, non-root,
# read-only root + a single writable /work mount (see backend/features/sandbox.py).
FROM python:3.12-slim

# Broad file/data/plot toolkit so the model can build essentially any artifact.
RUN pip install --no-cache-dir \
        python-pptx==1.0.2 \
        python-docx==1.1.2 \
        openpyxl==3.1.5 \
        XlsxWriter==3.2.0 \
        reportlab==4.2.5 \
        fpdf2==2.8.1 \
        pandas==2.2.3 \
        numpy==2.1.3 \
        matplotlib==3.9.2 \
        Pillow==11.0.0 \
        markdown==3.7 \
        beautifulsoup4==4.12.3 \
        lxml==5.3.0 \
        odfpy==1.4.1

# matplotlib without a display: headless backend + a writable config dir
ENV MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl \
    HOME=/tmp

# unprivileged user; the runner also drops caps and forbids new privileges
RUN useradd --create-home --uid 1000 sandbox
USER sandbox
WORKDIR /work
