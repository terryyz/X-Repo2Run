FROM ubuntu:focal-20231211

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y curl npm git nano wget vim unzip sudo cgroup-tools iproute2 iptables autoconf gperf flex bison bc && mkdir -p /workspace/download

# Python environment setup with package managers
RUN apt-get install -y python3-pip python3-dev
RUN pip3 install pytest pipdeptree
# Poetry installation
RUN curl -sSL https://install.python-poetry.org
ENV PATH="/root/.local/bin:$PATH"
# Pipenv installation
RUN pip3 install pipenv
# Conda installation
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /workspace/download/miniconda.sh \
    && bash /workspace/download/miniconda.sh -b -p /opt/conda \
    && rm /workspace/download/miniconda.sh
ENV PATH="/opt/conda/bin:$PATH"

# golang 1.23.3
RUN curl -o /workspace/download/go.tar.gz -SL https://go.dev/dl/go1.23.3.linux-amd64.tar.gz     && tar -zxf /workspace/download/go.tar.gz -C /usr/local && rm /workspace/download/go.tar.gz
ENV PATH=/bin:/usr/local/go/bin:$PATH

# nodejs 20.11.0
RUN curl -o /workspace/download/node.tar.gz -SL https://nodejs.org/dist/v20.11.0/node-v20.11.0-linux-x64.tar.gz     && mkdir -p /usr/local/lib/nodejs && tar -zxf /workspace/download/node.tar.gz -C /usr/local/lib/nodejs && mv /usr/local/lib/nodejs/node-v20.11.0-linux-x64 /usr/local/lib/nodejs/node     && rm /workspace/download/node.tar.gz
ENV PATH=/usr/local/lib/nodejs/node/bin:$PATH
ENV NODE_PATH=/usr/local/lib/node_modules
RUN npm install -g typescript@5.3.3 tsx@4.7.1 jest

# gcc 9
RUN sudo apt-get install -y build-essential && sudo apt-get install -y g++

# jdk 21
RUN curl -o /workspace/download/jdk.tar.gz -SL https://download.oracle.com/java/21/latest/jdk-21_linux-x64_bin.tar.gz     && mkdir /usr/java && tar -zxf /workspace/download/jdk.tar.gz -C /usr/java && rm /workspace/download/jdk.tar.gz     && java_path=`ls /usr/java/${path}` && echo "export JAVA_HOME=/usr/java/${java_path}" >> ~/.profile
RUN wget -O ~/gradle-4.2.1-bin.zip https://services.gradle.org/distributions/gradle-4.2.1-bin.zip && sudo apt-get install unzip && sudo mkdir /opt/gradle && sudo unzip -d /opt/gradle ~/gradle-4.2.1-bin.zip && rm ~/gradle-4.2.1-bin.zip && echo "export PATH=\$PATH:/opt/gradle/gradle-4.2.1/bin" >> ~/.bashrc
RUN echo "export PATH=\$PATH:/opt/gradle/gradle-4.2.1/bin" >> ~/.bashrc
    
# dotnet 8.0
RUN wget https://packages.microsoft.com/config/ubuntu/20.04/packages-microsoft-prod.deb -O packages-microsoft-prod.deb     && dpkg -i packages-microsoft-prod.deb && rm packages-microsoft-prod.deb     && apt-get update     && apt-get install -y dotnet-sdk-8.0

# php 7.4.3
RUN apt-get install -y php-cli=2:7.4+75

# rust
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y --default-toolchain 1.76.0
ENV PATH="/root/.cargo/bin:${PATH}"

# R, lua, ruby, julia, perl, scala
RUN apt-get install -y r-base lua5.2 luarocks ruby-full julia scala     && luarocks install luaunit     && PERL_MM_USE_DEFAULT=1 cpan Test::Deep Data::Compare

SHELL ["sh", "-lc"]
RUN update-alternatives --install /usr/bin/java java $JAVA_HOME/bin/java 20000     && update-alternatives --install /usr/bin/javac javac $JAVA_HOME/bin/javac 20000     && rm -r /workspace/download     && env
