import React, { useState, useEffect } from "react";
import axios from "axios";
import "./App.css";

const API_URL = "http://localhost:8000";

function App() {
    const [users, setUsers] = useState([]);
    const [showForm, setShowForm] = useState(false);
    const [editingUser, setEditingUser] = useState(null);
    const [formData, setFormData] = useState({
        full_name: "",
        username: "",
        password: "",
        gender: "",
        profile_pic: null,
    });
    const [previewImage, setPreviewImage] = useState(null);

    // AI Search state
    const [searchQuery, setSearchQuery] = useState("");
    const [isSearching, setIsSearching] = useState(false);
    const [searchInfo, setSearchInfo] = useState(null);

    // Fetch all users from backend
    useEffect(() => {
        fetchAllUsers();
    }, []);

    // Debounced search - wait 600ms after user stops typing
    useEffect(() => {
        if (searchQuery.trim() === "") {
            fetchAllUsers();
            return;
        }

        setIsSearching(true);
        const timeoutId = setTimeout(() => {
            performSearch(searchQuery);
        }, 600);

        return () => clearTimeout(timeoutId);
    }, [searchQuery]);

    const fetchAllUsers = async () => {
        try {
            const res = await axios.get(`${API_URL}/users/`);
            setUsers(res.data);
            setSearchInfo(null);
            setIsSearching(false);
        } catch (err) {
            console.error("Error fetching users:", err);
            setIsSearching(false);
        }
    };

    const performSearch = async (query) => {
        try {
            const res = await axios.get(`${API_URL}/ai/search`, {
                params: { query }
            });
            setUsers(res.data.results);
            setSearchInfo({
                count: res.data.count,
                message: res.data.message
            });
        } catch (err) {
            console.error("Error searching users:", err);
            setUsers([]);
            setSearchInfo(null);
        } finally {
            setIsSearching(false);
        }
    };

    // Handle input change in form
    const handleInputChange = (e) => {
        const { name, value } = e.target;
        setFormData({ ...formData, [name]: value });
    };

    // Handle profile picture file selection
    const handleFileChange = (e) => {
        const file = e.target.files[0];
        setFormData({ ...formData, profile_pic: file });

        if (file) {
            const reader = new FileReader();
            reader.onloadend = () => setPreviewImage(reader.result);
            reader.readAsDataURL(file);
        }
    };

    // Submit form to add or update user
    const handleSubmit = async (e) => {
        e.preventDefault();

        const data = new FormData();
        data.append("full_name", formData.full_name);
        data.append("username", formData.username);
        data.append("password", formData.password);
        data.append("gender", formData.gender);
        if (formData.profile_pic) data.append("profile_pic", formData.profile_pic);

        try {
            if (editingUser) {
                await axios.put(`${API_URL}/users/${editingUser.id}`, data, {
                    headers: { "Content-Type": "multipart/form-data" },
                });
            } else {
                await axios.post(`${API_URL}/users/`, data, {
                    headers: { "Content-Type": "multipart/form-data" },
                });
            }

            // Refresh list based on current search state
            if (searchQuery.trim()) {
                performSearch(searchQuery);
            } else {
                fetchAllUsers();
            }
            resetForm();
            setShowForm(false);
        } catch (err) {
            console.error("Error saving user:", err);
            alert("Error saving user. Check if username is unique.");
        }
    };

    // Edit user
    const handleEdit = (user) => {
        setEditingUser(user);
        setFormData({
            full_name: user.full_name,
            username: user.username,
            password: "",
            gender: user.gender,
            profile_pic: null,
        });
        setPreviewImage(user.profile_pic ? `${API_URL}/${user.profile_pic}` : null);
        setShowForm(true);
    };

    // Delete user
    const handleDelete = async (id) => {
        if (!window.confirm("Are you sure you want to delete this user?")) return;
        try {
            await axios.delete(`${API_URL}/users/${id}`);

            // Refresh based on current view
            if (searchQuery.trim()) {
                performSearch(searchQuery);
            } else {
                fetchAllUsers();
            }
        } catch (err) {
            console.error("Error deleting user:", err);
        }
    };

    // Reset form
    const resetForm = () => {
        setFormData({
            full_name: "",
            username: "",
            password: "",
            gender: "",
            profile_pic: null,
        });
        setPreviewImage(null);
        setEditingUser(null);
    };

    // Cancel form
    const cancelForm = () => {
        resetForm();
        setShowForm(false);
    };

    // Generate a colored placeholder image with initials
    const generateInitialsImage = (fullName, gender) => {
        const initials = fullName
            .split(" ")
            .map((n) => n[0].toUpperCase())
            .join("")
            .slice(0, 2);

        let bgColor;
        switch (gender) {
            case "Male":
                bgColor = "#3B82F6"; // blue
                break;
            case "Female":
                bgColor = "#EC4899"; // pink
                break;
            case "Other":
                bgColor = "#8B5CF6"; // purple
                break;
            default:
                bgColor = "#9CA3AF"; // gray
        }

        const canvas = document.createElement("canvas");
        canvas.width = 64;
        canvas.height = 64;
        const ctx = canvas.getContext("2d");

        ctx.fillStyle = bgColor;
        ctx.fillRect(0, 0, 64, 64);

        ctx.fillStyle = "#fff";
        ctx.font = "bold 28px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(initials, 32, 32);

        return canvas.toDataURL();
    };

    return (
        <div className="min-h-screen bg-gray-100 py-8 px-4">
            <div className="max-w-6xl mx-auto">
                {/* Header */}
                <div className="flex justify-between items-center mb-6">
                    <h1 className="text-3xl font-bold text-gray-800">
                        User Management
                    </h1>
                    <button
                        onClick={() => setShowForm(!showForm)}
                        className="bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-6 rounded-lg"
                    >
                        {showForm ? "Cancel" : "Add User"}
                    </button>
                </div>

                {/* Form */}
                {showForm && (
                    <form
                        onSubmit={handleSubmit}
                        className="bg-white p-6 rounded-lg shadow-md mb-6 animate-fadeIn"
                    >
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <input
                                type="text"
                                name="full_name"
                                value={formData.full_name}
                                onChange={handleInputChange}
                                placeholder="Full Name"
                                required
                                className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
                            />
                            <input
                                type="text"
                                name="username"
                                value={formData.username}
                                onChange={handleInputChange}
                                placeholder="Username"
                                required
                                className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
                            />
                            <input
                                type="password"
                                name="password"
                                value={formData.password}
                                onChange={handleInputChange}
                                placeholder={editingUser ? "Leave blank to keep password" : "Password"}
                                required={!editingUser}
                                className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
                            />
                            <select
                                name="gender"
                                value={formData.gender}
                                onChange={handleInputChange}
                                required
                                className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
                            >
                                <option value="">Select Gender</option>
                                <option value="Male">Male</option>
                                <option value="Female">Female</option>
                                <option value="Other">Other</option>
                            </select>
                        </div>

                        {/* Profile Pic */}
                        <div className="mt-4">
                            <input
                                type="file"
                                accept="image/*"
                                onChange={handleFileChange}
                                className="w-full"
                            />
                            {previewImage && (
                                <img
                                    src={previewImage}
                                    alt="Preview"
                                    className="w-16 h-16 mt-2 object-cover rounded-full border"
                                />
                            )}
                        </div>

                        <div className="mt-4 flex gap-4">
                            <button
                                type="submit"
                                className="bg-green-600 hover:bg-green-700 text-white font-semibold py-2 px-6 rounded-lg"
                            >
                                {editingUser ? "Update" : "Create"}
                            </button>
                            <button
                                type="button"
                                onClick={cancelForm}
                                className="bg-gray-500 hover:bg-gray-600 text-white font-semibold py-2 px-6 rounded-lg"
                            >
                                Cancel
                            </button>
                        </div>
                    </form>
                )}

                {/* AI Search Bar */}
                <div className="bg-white p-4 rounded-lg shadow-md mb-6 animate-fadeIn">
                    <div className="relative">
                        <input
                            type="text"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            placeholder='🔍 Smart search... Try "female users" or "users named Taylor" or "list all male"'
                            className="w-full px-4 py-3 pr-12 border rounded-lg focus:ring-2 focus:ring-blue-500 text-gray-700"
                        />
                        {isSearching && (
                            <div className="absolute right-4 top-1/2 transform -translate-y-1/2">
                                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                            </div>
                        )}
                        {searchQuery && !isSearching && (
                            <button
                                onClick={() => setSearchQuery("")}
                                className="absolute right-4 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600 text-xl"
                            >
                                ✕
                            </button>
                        )}
                    </div>

                    {/* Search Info */}
                    {searchInfo && (
                        <div className="mt-2 text-sm text-gray-600">
                            {searchInfo.message || `Found ${searchInfo.count} user${searchInfo.count !== 1 ? 's' : ''}`}
                        </div>
                    )}
                    {searchQuery && users.length === 0 && !isSearching && (
                        <div className="mt-2 text-sm text-gray-500">
                            No users found matching "{searchQuery}"
                        </div>
                    )}
                </div>

                {/* Users Table */}
                <div className="bg-white p-6 rounded-lg shadow-md animate-fadeIn">
                    {users.length > 0 ? (
                        <table className="min-w-full text-left">
                            <thead className="border-b bg-gray-50">
                            <tr>
                                <th className="px-4 py-2">Avatar</th>
                                <th className="px-4 py-2">Full Name</th>
                                <th className="px-4 py-2">Username</th>
                                <th className="px-4 py-2">Gender</th>
                                <th className="px-4 py-2">Actions</th>
                            </tr>
                            </thead>
                            <tbody>
                            {users.map((user) => (
                                <tr key={user.id} className="border-b hover:bg-gray-50 card">
                                    <td className="px-4 py-2">
                                        {user.profile_pic ? (
                                            <img
                                                src={`${API_URL}/${user.profile_pic}`}
                                                alt={user.full_name}
                                                className="w-16 h-16 rounded-full object-cover border"
                                            />
                                        ) : (
                                            <img
                                                src={generateInitialsImage(user.full_name, user.gender)}
                                                alt={user.full_name}
                                                className="w-16 h-16 rounded-full border"
                                            />
                                        )}
                                    </td>
                                    <td className="px-4 py-2">{user.full_name}</td>
                                    <td className="px-4 py-2">@{user.username}</td>
                                    <td className="px-4 py-2">
                                        <span
                                            className={`px-2 py-1 rounded-full text-white text-sm ${
                                                user.gender === "Male"
                                                    ? "bg-blue-500"
                                                    : user.gender === "Female"
                                                        ? "bg-pink-500"
                                                        : "bg-purple-500"
                                            }`}
                                        >
                                          {user.gender}
                                        </span>
                                    </td>
                                    <td className="px-4 py-2 flex gap-2">
                                        <button
                                            onClick={() => handleEdit(user)}
                                            className="bg-yellow-500 hover:bg-yellow-600 text-white px-4 py-2 rounded-lg"
                                        >
                                            Edit
                                        </button>
                                        <button
                                            onClick={() => handleDelete(user.id)}
                                            className="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-lg"
                                        >
                                            Delete
                                        </button>
                                    </td>
                                </tr>
                            ))}
                            </tbody>
                        </table>
                    ) : (
                        <div className="text-center py-8 text-gray-500">
                            {isSearching ? "Searching..." : "No users found"}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

export default App;