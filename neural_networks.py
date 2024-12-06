import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MultiLabelBinarizer, LabelEncoder, MinMaxScaler
from sklearn.metrics import classification_report
import torch
import torch.nn as nn
import matplotlib.pyplot as plt

# Load and preprocess data
def load_data(file_path, success_threshold=10_000):
    data = pd.read_csv(file_path)

    # Define success as a binary classification
    data['success'] = (data['listeners_lastfm'] > success_threshold).astype(int)

    # Process genres
    data['filtered_tags'] = data['filtered_tags'].apply(eval)
    mlb = MultiLabelBinarizer()
    genres_encoded = mlb.fit_transform(data['filtered_tags'])

    # Process countries
    le = LabelEncoder()
    countries_encoded = le.fit_transform(data['country_lastfm'])

    # Combine features
    X = pd.concat([
        pd.DataFrame(genres_encoded, columns=mlb.classes_),
        pd.DataFrame(countries_encoded, columns=['country'])
    ], axis=1)

    # Add log transformation for skewed features
    data['log_listeners_lastfm'] = np.log1p(data['listeners_lastfm'])
    X['log_listeners_lastfm'] = data['log_listeners_lastfm']

    # Normalize features
    scaler = MinMaxScaler()
    X = scaler.fit_transform(X)

    # Convert to tensors
    X_tensor = torch.tensor(X, dtype=torch.float32)
    y_tensor = torch.tensor(data['success'].values, dtype=torch.float32)

    return X_tensor, y_tensor, mlb, le, scaler, data

# Split data
def split_data(X, y, test_size=0.3, val_size=0.5, random_state=42):
    torch.manual_seed(random_state) # Using this for reproducibility
    torch.cuda.manual_seed_all(random_state) # Using this for reproducibility
    X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=test_size, random_state=random_state)
    X_test, X_val, y_test, y_val = train_test_split(X_temp, y_temp, test_size=val_size, random_state=random_state)
    return X_train, X_test, X_val, y_train, y_test, y_val

# Define the neural network
class MultiLayerNet(nn.Module):
    def __init__(self, input_dim):
        super(MultiLayerNet, self).__init__()
        self.fc1 = nn.Linear(input_dim, 128)
        self.relu1 = nn.ReLU()
        self.fc2 = nn.Linear(128, 64)
        self.relu2 = nn.ReLU()
        self.fc3 = nn.Linear(64, 1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        x = self.fc1(x)
        x = self.relu1(x)
        x = self.fc2(x)
        x = self.relu2(x)
        x = self.fc3(x)
        x = self.sigmoid(x)
        return x

# Train the model
def train_model(model, optimizer, criterion, X_train, y_train, X_val, y_val, num_epochs):
    train_losses = []
    val_losses = []

    for epoch in range(num_epochs):
        model.train()
        optimizer.zero_grad()
        outputs = model(X_train).squeeze()
        loss = criterion(outputs, y_train)
        loss.backward()
        optimizer.step()

        train_losses.append(loss.item())

        model.eval()
        with torch.no_grad():
            val_outputs = model(X_val).squeeze()
            val_loss = criterion(val_outputs, y_val)
            val_losses.append(val_loss.item())

        print(f"Epoch [{epoch + 1}/{num_epochs}], Train Loss: {loss.item():.4f}, Validation Loss: {val_loss.item():.4f}")

    return train_losses, val_losses

'''def print_top_genres_in_country(data, country, top_n=10):
    # Filter data for the specific country
    country_data = data[data['country_lastfm'] == country]

    # Explode the genre tags for the filtered data
    all_tags = country_data['filtered_tags'].explode()

    # Count and get the top genres
    top_genres = all_tags.value_counts().head(top_n)

    print(f"The top {top_n} most common genres in {country} are:")
    for genre, count in top_genres.items():
        print(f"{genre}: {count} occurrences")'''

def predict_success(model, X_train, le, mlb, data, country, genres):
    # Encode country
    try:
        country_encoded = le.transform([country])[0]
    except ValueError:
        print("Invalid country. Please try again.")
        return

    # Encode genres
    genres_set = set(genres)
    valid_genres = set(mlb.classes_)
    if not genres_set.issubset(valid_genres):
        print(f"Invalid genres. Valid genres are: {', '.join(valid_genres)}")
        return

    genres_encoded = mlb.transform([genres])[0]

    # Combine inputs
    user_input = np.zeros(X_train.shape[1])
    user_input[:len(genres_encoded)] = genres_encoded  # Set genre encoding
    user_input[len(genres_encoded)] = country_encoded  # Set country encoding

    # Add a placeholder for the numerical feature (log_listeners_lastfm)
    user_input[-1] = data['log_listeners_lastfm'].mean()

    # Normalize the input using the same scaler
    user_input_scaled = scaler.transform([user_input])

    # Convert to tensor and predict
    user_tensor = torch.tensor(user_input_scaled, dtype=torch.float32)
    model.eval()
    with torch.no_grad():
        output = model(user_tensor).item()
        success_rate = output * 100  # Convert to percentage
        print(f"Predicted Success Rate: {success_rate:.2f}%")

def evaluate_model(model, X, y):
    with torch.no_grad():
        predictions = model(X).squeeze()
        predicted_labels = (predictions > 0.5).float().numpy()
        true_labels = y.numpy()

    # Calculate and print classification report
    report = classification_report(true_labels, predicted_labels, target_names=['Not Successful', 'Successful'])
    print(report)

# Calculate accuracy
def calculate_accuracy(model, X, y):
    with torch.no_grad():
        predictions = model(X).squeeze()
        predicted_labels = (predictions > 0.5).float()
        accuracy = (predicted_labels == y).float().mean().item()
    return accuracy

# Main script
if __name__ == "__main__":
    # Load and preprocess data
    file_path = "filtered_data.csv"
    X, y, mlb, le, scaler, data = load_data(file_path)
        
    #print_top_genres_in_country(data, 'Germany')

    # Split data
    X_train, X_test, X_val, y_train, y_test, y_val = split_data(X, y)

    # Initialize the model
    input_dim = X_train.shape[1]
    model = MultiLayerNet(input_dim)

    # Define loss and optimizer
    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)

    # Train the model
    num_epochs = 40
    train_losses, val_losses = train_model(model, optimizer, criterion, X_train, y_train, X_val, y_val, num_epochs)

    # Plot training and validation losses
    plt.figure(figsize=(10, 5))
    plt.plot(train_losses, label='Training Loss')
    plt.plot(val_losses, label='Validation Loss')
    plt.xlabel('Epoch')
    plt.ylabel('Loss')
    plt.title('Training and Validation Loss')
    plt.legend()
    plt.show()


    # Evaluate the model
    print("Train Evaluation:")
    evaluate_model(model, X_train, y_train)

    print("Test Evaluation:")
    evaluate_model(model, X_test, y_test)

    # Get user input for prediction
    country = input("Enter the country: ").strip()
    genres = input("Enter genres (comma-separated): ").strip().split(',')

    # Predict success rate
    predict_success(model, X_train, le, mlb, data, country, genres)