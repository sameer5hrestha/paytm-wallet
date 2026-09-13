FROM maven:3.9.11-eclipse-temurin-17 AS build
WORKDIR /build
COPY pom.xml .
RUN mvn -B dependency:go-offline
COPY src src
RUN mvn -B package

FROM eclipse-temurin:17-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* && groupadd --gid 10001 wallet && useradd --uid 10001 --gid wallet --no-create-home wallet
WORKDIR /app
COPY --from=build --chown=wallet:wallet /build/target/paytm-wallet-1.0.0.jar app.jar
USER 10001:10001
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=65 -XX:+ExitOnOutOfMemoryError"
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=5 CMD curl -fsS http://127.0.0.1:${PORT:-8080}/health || exit 1
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
