FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /source
COPY src/SimpleApi.csproj src/packages.lock.json ./src/
RUN dotnet restore src/SimpleApi.csproj --locked-mode
COPY src/ ./src/
RUN dotnet publish src/SimpleApi.csproj --configuration Release --no-restore --output /app /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:10.0-noble-chiseled-extra AS runtime
WORKDIR /app
ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080
COPY --from=build /app ./
USER $APP_UID
ENTRYPOINT ["dotnet", "SimpleApi.dll"]