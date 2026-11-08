using System.Globalization;
using System.Net;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Shouldly;
using Xunit;

namespace SimpleApi.Tests;

public class AppEndpointTests(WebApplicationFactory<Program> factory)
    : IClassFixture<WebApplicationFactory<Program>>
{
    [Theory]
    [InlineData("Development")]
    [InlineData("Production")]
    public async Task Should_ReturnHealthy_When_HealthEndpointRequested(string environment)
    {
        using var app = factory.WithWebHostBuilder(builder => builder.UseEnvironment(environment));
        using var client = app.CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false });

        using var response = await client.GetAsync("/health", TestContext.Current.CancellationToken);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
        response.Content.Headers.ContentType?.MediaType.ShouldBe("text/plain");
        (await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken)).ShouldBe("Healthy");
    }

    [Theory]
    [InlineData("Development")]
    [InlineData("Production")]
    public async Task Should_ReturnFiveValidForecasts_When_WeatherEndpointRequested(string environment)
    {
        using var app = factory.WithWebHostBuilder(builder => builder.UseEnvironment(environment));
        using var client = app.CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false });
        var dateBeforeRequest = DateOnly.FromDateTime(DateTime.Now);

        using var response = await client.GetAsync("/weatherforecast", TestContext.Current.CancellationToken);
        var dateAfterRequest = DateOnly.FromDateTime(DateTime.Now);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
        response.Content.Headers.ContentType?.MediaType.ShouldBe("application/json");
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        var forecasts = document.RootElement.EnumerateArray().ToArray();
        forecasts.Length.ShouldBe(5);
        string[] allowedSummaries = ["Freezing", "Bracing", "Chilly", "Cool", "Mild", "Warm", "Balmy", "Hot", "Sweltering", "Scorching"];

        for (var index = 0; index < forecasts.Length; index++)
        {
            var forecast = forecasts[index];
            var date = DateOnly.ParseExact(forecast.GetProperty("date").GetString()!, "yyyy-MM-dd", CultureInfo.InvariantCulture);
            date.ShouldBeInRange(dateBeforeRequest.AddDays(index + 1), dateAfterRequest.AddDays(index + 1));
            var temperatureC = forecast.GetProperty("temperatureC").GetInt32();
            temperatureC.ShouldBeInRange(-20, 54);
            allowedSummaries.ShouldContain(forecast.GetProperty("summary").GetString()!);
            var expectedTemperatureF = 32 + decimal.ToInt32(decimal.Truncate(temperatureC / 0.5556m));
            forecast.GetProperty("temperatureF").GetInt32().ShouldBe(expectedTemperatureF);
        }
    }

    [Fact]
    public async Task Should_ReturnWeatherSchema_When_OpenApiRequestedInDevelopment()
    {
        using var app = factory.WithWebHostBuilder(builder => builder.UseEnvironment("Development"));
        using var client = app.CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false });

        using var response = await client.GetAsync("/openapi/v1.json", TestContext.Current.CancellationToken);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
        response.Content.Headers.ContentType?.MediaType.ShouldBe("application/json");
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        var root = document.RootElement;
        root.GetProperty("openapi").GetString().ShouldStartWith("3.");
        var operation = root.GetProperty("paths").GetProperty("/weatherforecast").GetProperty("get");
        operation.GetProperty("operationId").GetString().ShouldBe("GetWeatherForecast");
        var responseSchema = operation.GetProperty("responses").GetProperty("200")
            .GetProperty("content").GetProperty("application/json").GetProperty("schema");
        responseSchema.GetProperty("type").GetString().ShouldBe("array");
        responseSchema.GetProperty("items").GetProperty("$ref").GetString().ShouldBe("#/components/schemas/WeatherForecast");
        var properties = root.GetProperty("components").GetProperty("schemas")
            .GetProperty("WeatherForecast").GetProperty("properties");
        properties.GetProperty("date").GetProperty("type").GetString().ShouldBe("string");
        properties.GetProperty("date").GetProperty("format").GetString().ShouldBe("date");
        properties.GetProperty("temperatureC").GetProperty("type").EnumerateArray()
            .Select(type => type.GetString()).ShouldBe(["integer", "string"]);
        properties.GetProperty("temperatureF").GetProperty("type").EnumerateArray()
            .Select(type => type.GetString()).ShouldBe(["integer", "string"]);
        properties.GetProperty("summary").GetProperty("type").EnumerateArray()
            .Select(type => type.GetString()).Order(StringComparer.Ordinal).ShouldBe(["null", "string"]);
    }

    [Theory]
    [InlineData("Production")]
    [InlineData("Staging")]
    public async Task Should_ReturnNotFound_When_OpenApiRequestedOutsideDevelopment(string environment)
    {
        using var app = factory.WithWebHostBuilder(builder => builder.UseEnvironment(environment));
        using var client = app.CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false });

        using var response = await client.GetAsync("/openapi/v1.json", TestContext.Current.CancellationToken);

        response.StatusCode.ShouldBe(HttpStatusCode.NotFound);
        (await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken)).ShouldBeEmpty();
    }

    [Theory]
    [InlineData("Development")]
    [InlineData("Production")]
    public async Task Should_ReturnNotFound_When_UnknownRouteRequested(string environment)
    {
        using var app = factory.WithWebHostBuilder(builder => builder.UseEnvironment(environment));
        using var client = app.CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false });

        using var response = await client.GetAsync("/missing-route", TestContext.Current.CancellationToken);

        response.StatusCode.ShouldBe(HttpStatusCode.NotFound);
        (await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken)).ShouldBeEmpty();
    }

    [Fact]
    public async Task Should_ReturnMethodNotAllowed_When_WeatherEndpointPosted()
    {
        using var app = factory.WithWebHostBuilder(builder => builder.UseEnvironment("Production"));
        using var client = app.CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false });
        using var content = new StringContent("");

        using var response = await client.PostAsync("/weatherforecast", content, TestContext.Current.CancellationToken);

        response.StatusCode.ShouldBe(HttpStatusCode.MethodNotAllowed);
        response.Content.Headers.Allow.ShouldBe(["GET"]);
    }
}