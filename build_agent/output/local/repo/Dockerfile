FROM python:3.10
WORKDIR /
RUN apt-get update && apt-get install -y curl
RUN curl -sSL https://install.python-poetry.org | python -
ENV PATH="/root/.local/bin:$PATH"
RUN pip install pytest
RUN pip install pipdeptree
RUN git clone https://github.com/local/repo.git
RUN mkdir /repo
RUN git config --global --add safe.directory /repo
RUN cp -r /repo/. /repo && rm -rf /repo/
RUN rm -rf /repo
RUN pip install flask==3.1.0
RUN pip install flask_restful==0.3.10