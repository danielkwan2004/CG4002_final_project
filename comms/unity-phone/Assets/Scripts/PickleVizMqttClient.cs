using System;
using System.Collections.Concurrent;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using MQTTnet;
using MQTTnet.Client;
using MQTTnet.Protocol;
using TMPro;

public class PickleVizMqttClient : MonoBehaviour
{
    [Header("Broker settings")]
    public string brokerHost = "192.168.0.156";
    public int brokerPort = 8883;
    public string mqttUsername = "phone";
    public string mqttPassword = "phone_pw";

    [Header("Diagnostics")]
    public bool runTcpProbe = true;

    [Header("Topics")]
    public string sensorTopic = "fb/sensor/raw";
    public string resultTopic = "ultra96/ai/results";

    private IMqttClient mqttClient;
    public TMP_Text aiResultText;
    public TMP_Text sensorText;
    public TMP_Text statsText;
    public TMP_Text statusText;

    private readonly ConcurrentQueue<string> pendingMessages =
        new ConcurrentQueue<string>();

    private int sensorPacketCount = 0;
    private int aiResultCount = 0;
    private string latestSensorPayload = "";
    private string latestAIResult = "";
    private volatile bool mqttConnected = false;
    private volatile string connectionStatus = "Starting MQTT...";
    private volatile string connectionStage = "startup";
    private volatile string tlsFailure;
    private volatile bool connecting;
    private X509Certificate2 caCertificate;
    private CancellationTokenSource connectionLifetime;
    private long mqttBytes;
    private float statsStarted;
    private float mqttKbps;

    private async void Start()
    {
        statsStarted = Time.realtimeSinceStartup;
        connectionLifetime = new CancellationTokenSource();
        await RunConnectionLoopAsync(connectionLifetime.Token);
    }

    private async Task RunConnectionLoopAsync(CancellationToken cancellationToken)
    {
        int retrySeconds = 2;
        try
        {
            while (true)
            {
                cancellationToken.ThrowIfCancellationRequested();
                bool subscribed = await ConnectAsync(cancellationToken);
                if (subscribed)
                {
                    retrySeconds = 2;
                    while (mqttClient.IsConnected)
                        await Task.Delay(500, cancellationToken);
                }

                cancellationToken.ThrowIfCancellationRequested();
                string failure = connectionStatus;
                ReleaseConnection();
                for (int remaining = retrySeconds; remaining > 0; remaining--)
                {
                    connectionStatus = $"{failure}\nRetrying in {remaining}s...";
                    await Task.Delay(1000, cancellationToken);
                }
                retrySeconds = Math.Min(retrySeconds * 2, 30);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Scene destruction or application shutdown intentionally stops retries.
        }
        catch (Exception exception)
        {
            connectionStatus = $"MQTT reconnect loop stopped: {exception.Message}";
            Debug.LogException(exception);
        }
        finally
        {
            ReleaseConnection();
            connectionLifetime.Dispose();
            connectionLifetime = null;
        }
    }

    private void ReleaseConnection()
    {
        if (mqttClient != null)
        {
            mqttClient.ConnectedAsync -= OnConnected;
            mqttClient.DisconnectedAsync -= OnDisconnected;
            mqttClient.ApplicationMessageReceivedAsync -= OnMessageReceived;
            mqttClient.Dispose();
            mqttClient = null;
        }
        caCertificate?.Dispose();
        caCertificate = null;
        mqttConnected = false;
    }

    private void SetConnectionStage(string stage)
    {
        connectionStage = stage;
        connectionStatus = stage;
        Debug.Log($"MQTT: {stage}");
    }

    private async Task<bool> ConnectAsync(CancellationToken cancellationToken)
    {
        connecting = true;
        tlsFailure = null;
        try
        {
            SetConnectionStage("Loading CA resource...");
            // Unity strips only the final .txt extension from ca.crt.txt.
            TextAsset caAsset = Resources.Load<TextAsset>("ca.crt");
            if (caAsset == null)
                throw new InvalidOperationException(
                    "Missing Assets/Resources/ca.crt.txt");

            SetConnectionStage("Parsing CA certificate...");
            // Decode PEM explicitly rather than relying on platform-specific import support.
            const string begin = "-----BEGIN CERTIFICATE-----";
            const string end = "-----END CERTIFICATE-----";
            string pem = caAsset.text;
            int start = pem.IndexOf(begin, StringComparison.Ordinal);
            int finish = pem.IndexOf(end, StringComparison.Ordinal);
            if (start < 0 || finish <= start)
                throw new InvalidOperationException("CA resource must contain a PEM certificate");
            start += begin.Length;
            caCertificate = new X509Certificate2(
                Convert.FromBase64String(pem.Substring(start, finish - start)));
            Debug.Log($"MQTT CA: {caCertificate.Subject}; " +
                $"valid {caCertificate.NotBefore:u} to {caCertificate.NotAfter:u}; " +
                $"device UTC {DateTime.UtcNow:u}");

            SetConnectionStage("Creating MQTT client and TLS options...");
            mqttClient = new MqttFactory().CreateMqttClient();
            mqttClient.ConnectedAsync += OnConnected;
            mqttClient.DisconnectedAsync += OnDisconnected;
            mqttClient.ApplicationMessageReceivedAsync += OnMessageReceived;

            var tlsOptions = new MqttClientTlsOptionsBuilder()
                .UseTls()
                .WithSslProtocols(SslProtocols.Tls12)
                .WithCertificateValidationHandler(context =>
                {
                    SetConnectionStage("Validating broker TLS certificate...");
                    try
                    {
                        // Chain trust is handled below; hostname and missing-cert errors are fatal.
                        if (context.Certificate == null ||
                            (context.SslPolicyErrors & ~SslPolicyErrors.RemoteCertificateChainErrors) != 0)
                            throw new AuthenticationException(
                                $"Broker certificate error: {context.SslPolicyErrors}");

                        using (var serverCertificate = new X509Certificate2(context.Certificate))
                        using (var chain = new X509Chain())
                        {
                            chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
                            chain.ChainPolicy.VerificationFlags =
                                X509VerificationFlags.AllowUnknownCertificateAuthority;
                            chain.ChainPolicy.ExtraStore.Add(caCertificate);
                            bool valid = chain.Build(serverCertificate);
                            string errors = string.Join(", ", Array.ConvertAll(chain.ChainStatus,
                                status => $"{status.Status}: {status.StatusInformation.Trim()}"));
                            int count = chain.ChainElements.Count;
                            // ExtraStore alone does not require this CA to be the trust anchor.
                            bool trustedRoot = count > 0 && string.Equals(
                                chain.ChainElements[count - 1].Certificate.Thumbprint,
                                caCertificate.Thumbprint, StringComparison.OrdinalIgnoreCase);
                            if (!valid || !trustedRoot)
                                throw new AuthenticationException(
                                    $"Broker chain rejected (bundled CA match={trustedRoot}): {errors}");
                        }
                        SetConnectionStage("TLS certificate accepted; waiting for MQTT CONNACK...");
                        return true;
                    }
                    catch (Exception exception)
                    {
                        tlsFailure = exception.GetBaseException().Message;
                        Debug.LogError($"MQTT TLS validation failed: {exception}");
                        return false;
                    }
                })
                .Build();

            var options = new MqttClientOptionsBuilder()
                .WithClientId("phone")
                .WithTcpServer(brokerHost, brokerPort)
                .WithCredentials(mqttUsername, mqttPassword)
                .WithTimeout(TimeSpan.FromSeconds(15))
                .WithKeepAlivePeriod(TimeSpan.FromSeconds(10))
                .WithTlsOptions(tlsOptions)
                .Build();

            if (runTcpProbe)
                await ProbeTcpAsync(cancellationToken);

            SetConnectionStage($"Connecting TCP/TLS to {brokerHost}:{brokerPort} (15s timeout)...");
            var result = await mqttClient.ConnectAsync(options, cancellationToken);
            Debug.Log($"MQTT connect result: {result.ResultCode}");
            if (!mqttClient.IsConnected)
                throw new InvalidOperationException($"Broker rejected connection: {result.ResultCode}");
            return true;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            mqttConnected = mqttClient != null && mqttClient.IsConnected;
            connectionStatus = $"MQTT failed during {connectionStage}\n" +
                (tlsFailure ?? exception.GetBaseException().Message);
            Debug.LogError($"{connectionStatus}\n{exception}");
            return false;
        }
        finally
        {
            connecting = false;
        }
    }

    private async Task ProbeTcpAsync(CancellationToken cancellationToken)
    {
        SetConnectionStage($"Testing TCP to {brokerHost}:{brokerPort} (10s timeout)...");
        // This temporary connection sends no MQTT or TLS data. The broker may log EOF.
        using (var probe = new TcpClient())
        {
            Task connectTask = probe.ConnectAsync(brokerHost, brokerPort);
            Task completed = await Task.WhenAny(connectTask, Task.Delay(TimeSpan.FromSeconds(10), cancellationToken));
            if (completed != connectTask)
            {
                probe.Close();
                ObserveProbeCompletionAsync(connectTask);
                cancellationToken.ThrowIfCancellationRequested();
                throw new TimeoutException(
                    $"TCP probe timed out: Android cannot establish TCP to {brokerHost}:{brokerPort}. " +
                    "TLS and MQTT authentication have not started.");
            }

            await connectTask;
            Debug.Log($"MQTT TCP probe succeeded: {probe.Client.LocalEndPoint} -> " +
                $"{probe.Client.RemoteEndPoint}. Starting a separate MQTT/TLS connection next.");
        }
    }

    private static async void ObserveProbeCompletionAsync(Task connectTask)
    {
        // Closing a pending socket can complete its task with an exception later.
        try { await connectTask; }
        catch (Exception) { /* The timeout is already reported by ProbeTcpAsync. */ }
    }

    private async Task OnConnected(
        MqttClientConnectedEventArgs args
    )
    {
        mqttConnected = true;
        SetConnectionStage("MQTT connected; subscribing...");
        Debug.Log("Connected to MQTT broker");


        if (!mqttClient.IsConnected)
        {
            Debug.LogError("MQTT client is not connected after connection attempt.");
            return;
        }

        await mqttClient.SubscribeAsync(
            new MqttTopicFilterBuilder()
                .WithTopic(sensorTopic)
                .WithQualityOfServiceLevel(
                    MqttQualityOfServiceLevel.AtMostOnce
                )
                .Build()
        );

        await mqttClient.SubscribeAsync(
            new MqttTopicFilterBuilder()
                .WithTopic(resultTopic)
                .WithQualityOfServiceLevel(
                    MqttQualityOfServiceLevel.AtLeastOnce
                )
                .Build()
        );

        SetConnectionStage("MQTT Subscribed");
        Debug.Log("Subscribed to MQTT topics");
    }

    private Task OnDisconnected(
        MqttClientDisconnectedEventArgs args
    )
    {
        mqttConnected = false;
        string detail = args.Exception != null
            ? args.Exception.GetBaseException().Message
            : args.Reason.ToString();
        // ConnectAsync owns the failure status while connecting; do not hide its diagnostics.
        if (!connecting)
            connectionStatus = $"MQTT Disconnected: {detail}";
        Debug.LogWarning($"MQTT disconnected: {detail}\n{args.Exception}");
        return Task.CompletedTask;
    }

    private Task OnMessageReceived(
        MqttApplicationMessageReceivedEventArgs args
    )
    {
        string topic = args.ApplicationMessage.Topic;
        string payload = Encoding.UTF8.GetString(
            args.ApplicationMessage.PayloadSegment
        );

        pendingMessages.Enqueue(
            topic + "\n" + payload
        );
        mqttBytes += Encoding.UTF8.GetByteCount(payload);

        Debug.Log($"Received [{topic}]: {payload}");
        return Task.CompletedTask;
    }

    private void Update()
    {
        while (pendingMessages.TryDequeue(out string message))
        {
            int separator = message.IndexOf('\n');

            string topic = message.Substring(0, separator);
            string payload = message.Substring(separator + 1);

            if (topic == sensorTopic)
            {
                sensorPacketCount++;
                latestSensorPayload = payload;
            }
            else if (topic == resultTopic)
            {
                aiResultCount++;
                latestAIResult = payload;
            }
        }

        float elapsed = Time.realtimeSinceStartup - statsStarted;
        if (elapsed >= 5f)
        {
            mqttKbps = (float)(mqttBytes * 8.0 / elapsed / 1000.0);
            mqttBytes = 0;
            statsStarted = Time.realtimeSinceStartup;
        }

        if(statusText)
        {
            statusText.text = connectionStatus;
        }

        if (sensorText)
        {
            sensorText.text =
                $"Sensor packet: " + latestSensorPayload;
        }

        if (aiResultText)
        {
            aiResultText.text =
                $"AI result: " + latestAIResult;
        }

        if (statsText)
        {
            statsText.text =
                $"Sensor packets: {sensorPacketCount}\n" +
                $"AI results: {aiResultCount}\n" +
                $"\nMQTT receive: {mqttKbps:F2} kbps";
        }
    }

    private void OnApplicationQuit()
    {
        connectionLifetime?.Cancel();
    }

    private void OnDestroy()
    {
        connectionLifetime?.Cancel();
    }
}
