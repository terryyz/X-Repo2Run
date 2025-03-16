FROM python:3.10
RUN mkdir -p ~/.pip && touch ~/.pip/pip.conf
RUN echo "[global]" >> ~/.pip/pip.conf && echo "[install]" >> ~/.pip/pip.conf

# 安装必要的系统依赖
RUN apt-get update && apt-get install -y curl

# 安装 Poetry
RUN curl -sSL https://install.python-poetry.org | python -
# 将 Poetry 的 bin 目录添加到 PATH 环境变量
ENV PATH="/root/.local/bin:$PATH"

RUN pip install pytest

RUN pip install pipdeptree

RUN mkdir -p /repo && git config --global --add safe.directory /repo
        